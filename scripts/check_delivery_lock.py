#!/usr/bin/env python3
"""Guard: one delivery at a time — every way into a delivery holds the delivery lock (deploy/nas/release_ship.py, DeliveryLock).

On 2026-11-07 two sessions nearly ran a delivery at once. Both would have unpacked and built in the builder's one folder, and the link on the NAS
would have ended on whichever finished last; they agreed by message. The lock makes the second run stop, and this guard keeps every entry under it:

- ReleaseShip.ship and .back, ScoutShip.ship and .back take the lock before their first command and let it go after the last one, also when a
  command fails (a fake world here: the first command ends the run);
- a run that finds the lock taken stops before its first command and says the holder's note;
- the lock's own remote script, run on this machine with a real flock where there is one (Linux, CI): a second holder is refused with the first
  one's note, and the lock is free again once the first one ends.

The public mirror carries no deploy/nas/: there the guard says so and passes.
Negative self-test: scripts/test_guards_fail.py.

Run: python3 scripts/check_delivery_lock.py
"""
import importlib.util
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAS = ROOT / "deploy" / "nas"


class Stop(Exception):
    """The fake world ends a run at its first command: what happened before it is what the guard reads."""


class FakeStdin:
    """The session's stdin: closing it is how DeliveryLock lets the lock go."""

    def __init__(self, session):
        self.session = session

    def close(self):
        self.session.closed()


class FakeSession:
    """A lock session as DeliveryLock sees it: its first line, a stdin to close, a process to wait for."""

    def __init__(self, world, first_line, held):
        self.world = world
        self.held = held
        self.stdout = io.BytesIO(first_line)
        self.stderr = io.BytesIO(b"")
        self.stdin = FakeStdin(self)
        self.ended = False

    def closed(self):
        if self.held and not self.ended:
            self.world.events.append("unlock")
        self.ended = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class FakeMachines:
    """The two machines as a run sees them, writing down what it asked: the lock, then each command; the first command ends the run."""

    def __init__(self, busy_note=None):
        self.busy_note = busy_note
        self.events = []

    def hold(self, host, command):
        if self.busy_note is not None:
            return FakeSession(self, f"busy {self.busy_note}\n".encode(), held=False)
        self.events.append("lock")
        return FakeSession(self, b"held\n", held=True)

    def on(self, host, command, stdin=None):
        self.events.append("command")
        raise Stop(command)


class LocalMachines:
    """The lock's script run on this machine by sh, in place of ssh to the target: the real flock decides."""

    def hold(self, host, command):
        return subprocess.Popen(["sh", "-c", command], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class DeliveryLockGuard:
    """The four ways into a delivery, the refusal and the real lock, each checked; the problems found, in words."""

    BUSY_NOTE = "someone@elsewhere pid 7 since 2026-11-07 20:00:00 +0400: ReleaseShip.ship"

    def __init__(self, release, scout):
        self.release = release
        self.scout = scout
        self.problems = []

    def git(self, words, **_):
        """`git` for origin_main: the commit, without the network."""
        return subprocess.CompletedProcess(words, 0, stdout=b"abc1234\n", stderr=b"")

    def entries(self):
        release, scout = self.release, self.scout
        return {
            "ReleaseShip.ship": lambda machines: release.ReleaseShip(machines=machines, run=self.git).ship(),
            "ReleaseShip.back": lambda machines: release.ReleaseShip(machines=machines, run=self.git).back(),
            "ScoutShip.ship": lambda machines: scout.ScoutShip("machine", machines=machines, run=self.git).ship(),
            "ScoutShip.back": lambda machines: scout.ScoutShip("machine", machines=machines, run=self.git).back(),
        }

    def held_throughout(self):
        for name, entry in self.entries().items():
            world = FakeMachines()
            try:
                entry(world)
                self.problems.append(f"{name}: the fake world gave no command a run could end on — the guard read nothing")
                continue
            except Stop:
                pass
            except SystemExit as said:
                self.problems.append(f"{name}: stopped before its first command: {said}")
                continue
            events = world.events
            if "command" not in events:
                self.problems.append(f"{name}: sent no command")
            elif events[0] != "lock":
                self.problems.append(f"{name}: a command went before the delivery lock was taken ({events}) — two deliveries can run at once again")
            elif events[-1] != "unlock":
                self.problems.append(f"{name}: the lock was not let go when the run ended on a failed command ({events})")

    def refused_when_taken(self):
        for name, entry in self.entries().items():
            world = FakeMachines(busy_note=self.BUSY_NOTE)
            try:
                entry(world)
                self.problems.append(f"{name}: ran on while another delivery held the lock")
            except Stop:
                self.problems.append(f"{name}: sent a command while another delivery held the lock")
            except SystemExit as said:
                if self.BUSY_NOTE not in str(said):
                    self.problems.append(f"{name}: refused without the holder's note: {said}")

    def real_lock(self):
        """The script itself. Without flock on this machine (macOS) it cannot run here: said, and CI on Linux runs it."""
        if not (shutil.which("flock") and shutil.which("sh")):
            print("  the lock's script: flock is not on this machine, its run is CI's")
            return
        lock = self.release.DeliveryLock
        with tempfile.TemporaryDirectory(prefix="caravan-delivery-lock-") as tmp:
            path = f"{tmp}/.delivery.lock"
            with lock(LocalMachines(), "here", path, "the first holder"):
                try:
                    with lock(LocalMachines(), "here", path, "the second holder"):
                        self.problems.append("the lock's script: a second holder got the lock while the first held it")
                except SystemExit as said:
                    if "the first holder" not in str(said):
                        self.problems.append(f"the lock's script: the refusal does not name the holder: {said}")
            try:
                with lock(LocalMachines(), "here", path, "the third holder"):
                    pass
            except SystemExit as said:
                self.problems.append(f"the lock's script: the lock stayed taken after its holder ended: {said}")

    def run(self):
        self.held_throughout()
        self.refused_when_taken()
        self.real_lock()
        return self.problems


def load(name):
    """A module of deploy/nas by its file; registered by name, as scout_ship imports release_ship."""
    spec = importlib.util.spec_from_file_location(name, NAS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    if not (NAS / "release_ship.py").is_file():
        print("delivery lock: this tree has no deploy/nas/ (the public mirror) — nothing to guard")
        return 0
    problems = DeliveryLockGuard(load("release_ship"), load("scout_ship")).run()
    if problems:
        print("delivery lock: FAILED")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("delivery lock: ok — every delivery holds the lock, a taken lock stops the run before its first command")
    return 0


if __name__ == "__main__":
    sys.exit(main())
