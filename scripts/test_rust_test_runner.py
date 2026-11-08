#!/usr/bin/env python3
"""How scripts/rust_test_runner.py ends a test binary: at its limit, with the run that started it, on a word, and always with
everything the binary started.

2026-11-04: two hung tests of an abandoned `cargo test` spun a Mac for three days (the runner says the story). Each case starts the
real runner on a stand-in for a test binary: a small program in a `deps` folder that passes, fails, or spins and starts a grandchild
that spins too. Then it looks at what is still running. The old world — cargo starting the binary bare — fails every stopping case
here, by leaving the stand-in and its grandchild alive:

- a binary that passes or fails gives its own exit, with its arguments as cargo passed them;
- one that spins past the limit is stopped with its grandchild, and the run fails with 124 and a line that names it;
- one deaf to SIGTERM is stopped by SIGKILL after the grace;
- when cargo is killed outright, the runner stops the binary; when the runner itself is, its sentinel does;
- a runner told to stop (SIGTERM) stops the binary and goes by the same signal; a binary killed by a signal takes the runner with it;
- a program outside a `deps` folder (`cargo run`) runs in the runner's place, with no limit;
- a limit that is no number of seconds above zero is refused, and nothing runs (negative: there is no "no limit").

Run: python3 scripts/test_rust_test_runner.py
"""
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "scripts" / "rust_test_runner.py"

#: The stand-in for a test binary. Its first argument says what it does, its second is a file for what it has to say.
STAND_IN = r'''
import os, signal, subprocess, sys, time
mode, said = sys.argv[1], sys.argv[2]
if mode == "pass":
    sys.exit(0)
if mode == "fail":
    sys.exit(101)
if mode == "args":
    open(said, "w").write("\n".join(sys.argv[1:]))
    sys.exit(0)
if mode == "signal":
    os.kill(os.getpid(), signal.SIGUSR1)
    time.sleep(5)
    sys.exit(0)
if mode == "deaf":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
grandchild = subprocess.Popen([sys.executable, "-c", "while True: pass"])
open(said + ".part", "w").write(f"{os.getpid()} {grandchild.pid}\n")
os.replace(said + ".part", said)
while True:
    pass
'''

#: A stand-in for cargo: starts the runner on the spinning binary, writes the runner's pid to the file named first, and waits to be
#: killed.
CARGO = r'''
import os, subprocess, sys, time
runner = subprocess.Popen(sys.argv[2:])
open(sys.argv[1] + ".part", "w").write(f"{runner.pid}\n")
os.replace(sys.argv[1] + ".part", sys.argv[1])
time.sleep(600)
'''


class Processes:
    """What is still running, asked so that a dead process nobody has reaped yet (a zombie) counts as gone."""

    @staticmethod
    def alive(pid):
        stat = Path(f"/proc/{pid}/stat")
        if Path("/proc/self/stat").exists():
            try:
                return stat.read_text().rsplit(")", 1)[1].split()[0] != "Z"
            except (FileNotFoundError, ProcessLookupError):
                return False
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        return bool(state) and not state.startswith("Z")

    @classmethod
    def gone_within(cls, pids, seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            if not any(cls.alive(pid) for pid in pids):
                return True
            time.sleep(0.05)
        return not any(cls.alive(pid) for pid in pids)

    @classmethod
    def kill_left(cls, pids):
        """The net under a failed case: nothing this test started keeps spinning."""
        for pid in pids:
            if pid and cls.alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


class RunnerCases:
    """The runner on a stand-in in a folder laid out as cargo's: target/debug/deps for tests, target/debug for a program."""

    GRACE = 3.0

    def __init__(self, folder):
        self.folder = folder
        deps = folder / "target" / "debug" / "deps"
        deps.mkdir(parents=True)
        self.binary = self.write(deps / "stand_in-0123456789abcdef", STAND_IN)
        self.program = self.write(folder / "target" / "debug" / "stand_in", STAND_IN)
        self.failed = []
        self.count = 0
        self.said_by = {}

    @staticmethod
    def write(path, body):
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)
        return path

    def check(self, what, ok, detail=""):
        self.count += 1
        if not ok:
            self.failed.append(f"FAIL {what}{': ' + str(detail)[:400] if detail else ''}")

    def env(self, limit=None):
        env = {key: value for key, value in os.environ.items() if key != "CARAVAN_TEST_LIMIT"}
        if limit is not None:
            env["CARAVAN_TEST_LIMIT"] = limit
        return env

    def said(self, name):
        return self.folder / f"{name}.said"

    def wait_said(self, name, seconds=10):
        """The pids a stand-in wrote: the spinning binary itself and its grandchild, or the runner the stand-in for cargo started."""
        path = self.said(name)
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            if path.exists():
                return [int(word) for word in path.read_text().split()]
            time.sleep(0.02)
        return []

    def run(self, binary, *args, limit=None, seconds=20):
        process = self.start(binary, *args, limit=limit)
        code, stderr = self.finish(process, seconds)
        return subprocess.CompletedProcess(process.args, code, "", stderr)

    def start(self, binary, *args, limit=None):
        """The runner on `binary`, what it says going to a file. A file, not a pipe: a stand-in that a broken runner left alive
        holds a pipe open for ever, and a test that waits for the pipe's end would hang on the very thing it is here to catch."""
        said = tempfile.TemporaryFile(mode="w+", dir=self.folder)
        process = subprocess.Popen([str(RUNNER), str(binary), *args], env=self.env(limit), stderr=said, text=True)
        self.said_by[process.pid] = said
        return process

    def finish(self, process, seconds):
        """The runner's exit and what it said; None for an exit when it did not end in `seconds` (it is killed then)."""
        try:
            code = process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            code = None
        said = self.said_by.pop(process.pid)
        said.seek(0)
        words = said.read()
        said.close()
        return code, words if code is not None else f"did not end in {seconds} s; {words}"

    def passes_and_fails(self):
        done = self.run(self.binary, "pass", self.said("pass"))
        self.check("a binary that passes: exit 0", done.returncode == 0, done.stderr)
        done = self.run(self.binary, "fail", self.said("fail"))
        self.check("a binary that fails: its own exit, 101", done.returncode == 101, done.stderr)
        done = self.run(self.binary, "args", self.said("args"), "--quiet", "lines::tests", "--exact")
        said = self.said("args").read_text().split("\n") if self.said("args").exists() else []
        self.check("the arguments go through as cargo passed them",
                   said == ["args", str(self.said("args")), "--quiet", "lines::tests", "--exact"], (said, done.stderr))

    def spins_past_the_limit(self):
        pids = []
        try:
            process = self.start(self.binary, "spin", str(self.said("spin")), limit="1")
            pids = self.wait_said("spin")
            self.check("the spinning binary started its grandchild", len(pids) == 2, pids)
            started = time.monotonic()
            code, stderr = self.finish(process, 20)
            took = time.monotonic() - started
            self.check("a binary past its limit fails the run with 124", code == 124, stderr)
            # Stopped at the limit, the spinning stand-in goes at SIGTERM: well before the limit and the grace would add up to.
            self.check("it is stopped soon after the limit, not at the grace's end", took < 1 + self.GRACE - 0.5, f"{took:.2f}s")
            self.check("the line names the binary and the limit",
                       "stand_in-0123456789abcdef" in stderr and "предела 1 с" in stderr and "CARAVAN_TEST_LIMIT" in stderr, stderr)
            self.check("the binary and its grandchild are gone", Processes.gone_within(pids, 2), pids)
        finally:
            Processes.kill_left(pids)

    def deaf_to_sigterm(self):
        pids = []
        try:
            process = self.start(self.binary, "deaf", str(self.said("deaf")), limit="1")
            pids = self.wait_said("deaf")
            code, stderr = self.finish(process, 20)
            self.check("a binary deaf to SIGTERM still fails the run with 124", code == 124, stderr)
            self.check("SIGKILL after the grace takes it and its grandchild", Processes.gone_within(pids, 2), pids)
        finally:
            Processes.kill_left(pids)

    def cargo_killed_outright(self):
        pids, cargo, runner = [], None, None
        try:
            cargo = subprocess.Popen([sys.executable, "-c", CARGO, str(self.said("cargo-runner")), str(RUNNER), str(self.binary),
                                      "spin", str(self.said("cargo"))], env=self.env("600"), start_new_session=True)
            runner = (self.wait_said("cargo-runner") or [None])[0]
            pids = self.wait_said("cargo")
            self.check("under cargo, the binary started its grandchild", len(pids) == 2, pids)
            cargo.kill()
            cargo.wait(timeout=5)
            self.check("cargo killed outright: the runner stops the binary and its grandchild", Processes.gone_within(pids, 4), pids)
            self.check("and the runner itself goes", runner is not None and Processes.gone_within([runner], 4), runner)
        finally:
            Processes.kill_left([*pids, runner])
            if cargo is not None and cargo.poll() is None:
                cargo.kill()

    def runner_killed_outright(self):
        pids = []
        try:
            process = subprocess.Popen([str(RUNNER), str(self.binary), "spin", str(self.said("runner"))], env=self.env("600"))
            pids = self.wait_said("runner")
            process.kill()
            process.wait(timeout=5)
            self.check("the runner killed outright: its sentinel stops the binary and its grandchild",
                       Processes.gone_within(pids, self.GRACE + 2), pids)
        finally:
            Processes.kill_left(pids)

    def told_to_stop(self):
        pids = []
        try:
            process = self.start(self.binary, "spin", str(self.said("told")), limit="600")
            pids = self.wait_said("told")
            process.send_signal(signal.SIGTERM)
            code, stderr = self.finish(process, 20)
            self.check("a runner told SIGTERM goes by SIGTERM, as a bare binary would", code == -signal.SIGTERM, stderr)
            self.check("and says so", "SIGTERM" in stderr, stderr)
            self.check("the binary and its grandchild are gone with it", Processes.gone_within(pids, 2), pids)
        finally:
            Processes.kill_left(pids)

    def killed_by_a_signal(self):
        done = self.run(self.binary, "signal", self.said("signal"))
        self.check("a binary killed by a signal takes the runner with it, so cargo names the signal",
                   done.returncode == -signal.SIGUSR1, (done.returncode, done.stderr))

    def a_program_is_no_test(self):
        code = "import os, sys, time; time.sleep(1.5); open(sys.argv[2], 'w').write(str(os.getpid()))"
        self.write(self.program, code)
        process = self.start(self.program, "x", str(self.said("program")), limit="1")
        exit_code, stderr = self.finish(process, 20)
        self.check("a program outside deps/ runs with no limit", exit_code == 0, (exit_code, stderr))
        said = self.said("program").read_text() if self.said("program").exists() else "nothing"
        self.check("in the runner's place", said == str(process.pid), said)

    def bad_limits(self):
        for limit in ("0", "-1", "abc", "nan", "inf", ""):
            said = self.said(f"limit{len(limit)}{limit.strip('-')}")
            done = self.run(self.binary, "args", said, limit=limit)
            self.check(f"CARAVAN_TEST_LIMIT={limit!r} is refused with 2", done.returncode == 2, done.stderr)
            self.check(f"CARAVAN_TEST_LIMIT={limit!r} is named", "CARAVAN_TEST_LIMIT" in done.stderr, done.stderr)
            self.check(f"CARAVAN_TEST_LIMIT={limit!r} runs nothing", not said.exists())

    def all(self):
        for case in (self.passes_and_fails, self.spins_past_the_limit, self.deaf_to_sigterm, self.cargo_killed_outright,
                     self.runner_killed_outright, self.told_to_stop, self.killed_by_a_signal, self.a_program_is_no_test,
                     self.bad_limits):
            case()


def main():
    with tempfile.TemporaryDirectory(prefix="caravan-runner-") as folder:
        cases = RunnerCases(Path(folder))
        cases.all()
    if cases.failed:
        print("\n".join(cases.failed))
        raise SystemExit(f"rust test runner: {len(cases.failed)} of {cases.count} failed")
    print(f"rust test runner: ok — {cases.count} checks: a test binary ends at its limit, with its run, on a word, "
          f"and with everything it started")
    return 0


if __name__ == "__main__":
    sys.exit(main())
