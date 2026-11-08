#!/usr/bin/env python3
"""The one way cargo starts a Rust test binary: under a time limit, and for no longer than the run that started it.

2026-11-04: an agent started `cargo test -p wire -p rules` in the background, its output in a file. Two tests of `wire` hung in
a busy loop: the tests' source of bytes waited for ever after its last piece, and the test asked again at once after every wait.
libtest only said they had been running for over 60 seconds, cargo has no time limit, the agent never waited for the job, and the
`pkill` it sent named a binary that did not exist. When the run's parent was gone, the binary was handed to launchd and spun two
cores of the owner's Mac for three days and six hours, 148 hours of processor time, until the heat gave it away.

The root .cargo/config.toml names this file as the runner of every target, so a `cargo test` started anywhere in the tree, by CI,
by a script or by hand, starts each test binary through it (scripts/check_rust_test_start.py holds that). Here a test binary:
- runs in a process group of its own, so that it and everything it starts are stopped as one;
- is stopped once it has run for LIMIT seconds (CARAVAN_TEST_LIMIT sets another number on purpose), and the run fails with exit
  124 and a line on stderr that names the binary: a hang is red and loud, not quiet;
- is stopped when the run that started it is gone: the runner watches its parent, cargo, and a sentinel inside the binary's group
  watches the runner, so a runner killed outright leaves nothing running either;
- is stopped with its group when the runner is told to stop: SIGINT, SIGTERM, SIGHUP, SIGQUIT.
Stopping is SIGTERM to the group, then SIGKILL after GRACE seconds. A descendant that moves itself into a group of its own
(setsid) is out of reach, as it is for timeout(1).

A binary outside a `deps` folder is not a test: `cargo run` starts target/<profile>/<name>. It runs as it is, in this process's
place, with no limit.

Needs Python 3.11 or newer (subprocess's process_group). The behaviour is pinned by scripts/test_rust_test_runner.py.
"""
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


class Told(Exception):
    """A signal that tells the runner to stop."""

    def __init__(self, number):
        super().__init__(number)
        self.number = number


class BadLimit(ValueError):
    """A limit that is no number of seconds above zero."""


class GroupSentinel:
    """Stops a test binary's process group once the runner is gone, whatever way it went.

    It is the group's first member, forked from the runner before the binary starts, and it reads a pipe that only the runner
    holds open for writing. The pipe ends when the runner ends, by its own exit or by SIGKILL alike; then the sentinel stops the
    group: SIGTERM, up to `grace` seconds for the binary to go, then SIGKILL, which ends the sentinel too.
    """

    def __init__(self, pipe, group, grace):
        self.pipe = pipe
        self.group = group
        self.grace = grace

    def watch(self):
        """Waits for the runner to go, then stops the group. The runner writes the binary's pid first."""
        said = b""
        while chunk := os.read(self.pipe, 64):
            said += chunk
        words = said.split()
        self.stop(int(words[0]) if words else None)

    def stop(self, binary):
        self.signal(signal.SIGTERM)
        until = time.monotonic() + self.grace
        while binary is not None and self.alive(binary) and time.monotonic() < until:
            time.sleep(0.05)
        self.signal(signal.SIGKILL)

    def signal(self, number):
        try:
            os.killpg(self.group, number)
        except ProcessLookupError:
            pass  # the group is empty already: nothing is left to stop

    @staticmethod
    def alive(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True


class TestBinaryRun:
    """One test binary, run under the limit, in a process group of its own, for no longer than the run that started it."""

    #: The longest a test binary may run, in seconds. The slowest binary of the workspace, the controller's 734 tests, took 9 s on
    #: the owner's Mac on 2026-11-08: the limit leaves room for a loaded machine, and a hang still costs minutes, not days. Under
    #: the CI job's own timeout, so that in CI too the runner, which names the binary, is what stops it.
    LIMIT = 300.0
    #: What sets another limit, in seconds, for a run that is long on purpose. There is no "no limit".
    LIMIT_VARIABLE = "CARAVAN_TEST_LIMIT"
    #: Seconds between SIGTERM and SIGKILL.
    GRACE = 3.0
    #: How often the runner looks at the clock and at its parent, in seconds.
    TICK = 0.25
    #: The exit of a binary stopped at its limit: timeout(1)'s.
    TIMED_OUT = 124
    #: The exit of a binary whose run is gone: nobody waits for it, but it says the run hung up.
    ABANDONED = 128 + signal.SIGHUP.value
    #: The exit when the runner will not start the binary: no binary named, or a limit that is no limit.
    REFUSED = 2
    STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT)

    def __init__(self, binary, args, limit, parent):
        self.binary = binary
        self.args = list(args)
        self.limit = limit
        self.parent = parent
        self.name = Path(binary).name
        self.group = None
        self.process = None

    @staticmethod
    def is_test(binary):
        """A test or a bench harness: cargo builds them into target/<profile>/deps."""
        return Path(binary).parent.name == "deps"

    @classmethod
    def limit_from(cls, environ):
        """The limit in seconds: LIMIT, or what CARAVAN_TEST_LIMIT says. Anything but a number above zero is refused, not guessed."""
        said = environ.get(cls.LIMIT_VARIABLE)
        if said is None:
            return cls.LIMIT
        try:
            seconds = float(said)
        except ValueError:
            seconds = math.nan
        if not math.isfinite(seconds) or seconds <= 0:
            raise BadLimit(f"{cls.LIMIT_VARIABLE}={said!r} — не число секунд больше нуля; предела «без предела» нет: "
                           f"так тест и крутился трое суток. Тесты не запущены.")
        return seconds

    @staticmethod
    def say(words):
        sys.stderr.write(f"rust_test_runner: {words}\n")
        sys.stderr.flush()

    def run(self):
        """The binary's exit, or how it was stopped."""
        for number in self.STOP_SIGNALS:
            signal.signal(number, self.told)
        pipe_out, pipe_in = os.pipe()
        sentinel = os.fork()
        if sentinel == 0:
            self.become_sentinel(pipe_out, pipe_in)
        self.group = sentinel
        try:
            os.setpgid(sentinel, sentinel)  # the sentinel does the same; whichever comes first, the binary's group exists
        except PermissionError:
            pass  # the sentinel has set it already
        os.close(pipe_out)
        try:
            self.process = subprocess.Popen([self.binary, *self.args], process_group=self.group)
            self.tell_sentinel(pipe_in)
            return self.supervise()
        except Told as told:
            self.say(f"получен {signal.Signals(told.number).name} — останавливаю {self.name} вместе со всем, что он запустил.")
            self.stop()
            return self.exit_like(-told.number)

    def told(self, number, _frame):
        raise Told(number)

    def tell_sentinel(self, pipe_in):
        """The binary's pid, for the sentinel to wait on. A sentinel already gone is said, and the runner still holds the limit."""
        try:
            os.write(pipe_in, f"{self.process.pid}\n".encode())
        except BrokenPipeError:
            self.say(f"сторож группы {self.name} пропал до старта: предел и присмотр за cargo остаются, но если раннер убьют "
                     f"через SIGKILL, {self.name} останется работать.")

    def become_sentinel(self, pipe_out, pipe_in):
        """The forked child: the first member of the binary's group, deaf to the signals the runner takes. Never returns."""
        try:
            os.setpgid(0, 0)
            os.close(pipe_in)
            for number in self.STOP_SIGNALS:
                signal.signal(number, signal.SIG_IGN)
            # The caller's pipes are let go: a `cargo test | tail` must not wait for the sentinel.
            quiet = os.open(os.devnull, os.O_RDWR)
            for stream in (0, 1, 2):
                os.dup2(quiet, stream)
            GroupSentinel(pipe_out, os.getpid(), self.GRACE).watch()
        finally:
            os._exit(0)

    def supervise(self):
        started = time.monotonic()
        while True:
            try:
                return self.exit_like(self.process.wait(timeout=self.TICK))
            except subprocess.TimeoutExpired:
                pass
            if time.monotonic() - started >= self.limit:
                # libtest names a test that runs long only after 60 seconds: with a shorter limit, the hung one is a test with no
                # "ok" of its own.
                hung = ("Зависший тест libtest назвал выше: «has been running for over 60 seconds»." if self.limit > 60 else
                        "Зависший тест — тот, у которого выше нет своего «ok».")
                self.say(f"{self.name} работает дольше предела {self.limit:g} с — останавливаю его вместе со всем, что он запустил "
                         f"(SIGTERM, через {self.GRACE:g} с SIGKILL). {hung} Дольше нарочно: {self.LIMIT_VARIABLE}=<секунды>.")
                self.stop()
                return self.TIMED_OUT
            if os.getppid() != self.parent:
                self.say(f"запуск, который начал {self.name}, пропал (родитель {self.parent} завершился) — "
                         f"останавливаю {self.name} вместе со всем, что он запустил.")
                self.stop()
                return self.ABANDONED

    def stop(self):
        """SIGTERM to the group, up to GRACE seconds for the binary, then SIGKILL to the group, the sentinel with it."""
        for number in self.STOP_SIGNALS:
            signal.signal(number, signal.SIG_IGN)  # a second word while stopping does not cut the stopping short
        sentinel = GroupSentinel(None, self.group, self.GRACE)
        sentinel.signal(signal.SIGTERM)
        if self.process is not None:
            try:
                self.process.wait(timeout=self.GRACE)
            except subprocess.TimeoutExpired:
                pass
        sentinel.signal(signal.SIGKILL)
        if self.process is not None:
            try:
                self.process.wait(timeout=self.GRACE)
            except subprocess.TimeoutExpired:
                self.say(f"{self.name} не ушёл и после SIGKILL (процесс {self.process.pid}).")

    def exit_like(self, code):
        """The binary's exit as this process's own: a binary killed by a signal kills the runner with it, so cargo says which."""
        if code >= 0:
            return code
        try:
            signal.signal(-code, signal.SIG_DFL)
        except (OSError, ValueError):
            pass  # SIGKILL has no handler to put back, and needs none: it ends the runner as it ended the binary
        os.kill(os.getpid(), -code)
        return 128 - code  # only a signal whose default ends a process ends a binary; should the runner outlive it, its number says it


def main(argv):
    """The entry: cargo passes the binary's path, then its arguments. A function because it only hands over to the class."""
    if not argv:
        TestBinaryRun.say("нечего запускать: cargo передаёт путь к бинарнику первым аргументом.")
        return TestBinaryRun.REFUSED
    binary, args = argv[0], argv[1:]
    if not TestBinaryRun.is_test(binary):
        os.execv(binary, [binary, *args])
    try:
        limit = TestBinaryRun.limit_from(os.environ)
    except BadLimit as refused:
        TestBinaryRun.say(str(refused))
        return TestBinaryRun.REFUSED
    return TestBinaryRun(binary, args, limit, os.getppid()).run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
