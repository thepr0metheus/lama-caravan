#!/usr/bin/env python3
"""Value snapshot: the tests' port pool (scripts/_ports.py, 1.3.569) — a port is given once per process, never twice.

test_proxy_forward.py asked the kernel for about 60 free ports before any of its servers bound, and the kernel may hand a port it has
just taken back to the very next asker: two servers got one number, and the second died with "Address already in use" (GitLab pipeline
30 of MR !130, once; green on the retry). The pool remembers what it gave and draws again on a repeat. Each claim has a pin that fails
if the memory is taken out.

The kernel is a stand-in here: a socket that answers from a script, so "the same port twice" is a fact of the test, not a matter of luck.

Run: python3 scripts/test_ports.py
"""
import socket
import sys

from _ports import PORTS, PortPool, free_port

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class ScriptedKernel:
    """A socket factory whose sockets answer, in turn, the ports of a script — and count what was opened and closed."""

    def __init__(self, ports, fail_bind=False):
        self.ports = list(ports)
        self.fail_bind = fail_bind
        self.opened = 0
        self.closed = 0

    def __call__(self):
        kernel = self
        kernel.opened += 1

        class Sock:
            def bind(self, address):
                assert address == ("127.0.0.1", 0), address
                if kernel.fail_bind:
                    raise OSError("no sockets left")

            def getsockname(self):
                return ("127.0.0.1", kernel.ports.pop(0))

            def close(self):
                kernel.closed += 1
        return Sock()


def main():
    print("a port is given once:")
    kernel = ScriptedKernel([5000, 5000, 5001, 5001, 5000, 5002])
    pool = PortPool(kernel)
    got = [pool.take(), pool.take(), pool.take()]
    check(got == [5000, 5001, 5002],
          f"the kernel offers 5000 twice in a row: the second ask gets 5001, the repeats are drawn again (got {got})")
    check(kernel.opened == 6 and kernel.closed == 6,
          f"every draw's socket is closed — the ones whose port was a repeat too (opened {kernel.opened}, closed {kernel.closed})")
    check(pool.given == {5000, 5001, 5002}, "the pool remembers what it gave, and only that")

    print("many asks, few ports:")
    cycling = ScriptedKernel([6000 + n % 150 for n in range(100 * 150)])
    pool = PortPool(cycling)
    many = [pool.take() for _ in range(100)]
    check(len(set(many)) == 100, "a hundred asks of a kernel that offers 150 numbers over and over: a hundred different ports")

    print("a kernel with no new port:")
    stuck = ScriptedKernel([7000] * 500)
    pool = PortPool(stuck)
    first = pool.take()
    try:
        pool.take()
        raised = None
    except RuntimeError as exc:
        raised = str(exc)
    check(first == 7000 and raised is not None and "200 draws" in raised,
          f"negative: the same port for ever is said after {PortPool.ATTEMPTS} draws, not looped on (got {raised!r})")
    check(stuck.opened == stuck.closed, f"and no draw leaves its socket open (opened {stuck.opened}, closed {stuck.closed})")

    print("a bind that fails:")
    broken = ScriptedKernel([8000], fail_bind=True)
    pool = PortPool(broken)
    try:
        pool.take()
        error = None
    except OSError as exc:
        error = str(exc)
    check(error == "no sockets left" and broken.closed == broken.opened == 1 and pool.given == set(),
          "negative: a failed bind is the kernel's answer, passed on as it is — the socket closed, nothing remembered as given")

    print("the pools:")
    one, other = PortPool(ScriptedKernel([9000])), PortPool(ScriptedKernel([9000]))
    check(one.take() == other.take() == 9000 and one.given is not other.given,
          "negative: two pools do not share a memory — only the process's own (PORTS) is the one every test draws from")
    port = free_port()
    check(port in PORTS.given and free_port() != port,
          "free_port() draws from the process's pool: what it gave is remembered, the next ask is another port")

    print("the real kernel:")
    real = [free_port() for _ in range(300)]
    check(len(set(real)) == 300, "three hundred asks of the real kernel: three hundred different ports")
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", real[0]))
        free_now = True
    except OSError:
        free_now = False
    finally:
        probe.close()
    check(free_now, "and a port the pool gave is free to bind (the pool hands out numbers, it does not hold them)")

    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for msg in _fail:
            print("  -", msg)
        return 1
    print("\nports OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
