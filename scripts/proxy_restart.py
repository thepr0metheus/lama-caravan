#!/usr/bin/env python3
"""Does this deploy restart the proxy? scripts/deploy.sh asks, this answers.

The proxy carries every agent's traffic: restarting it drops every open
connection, and a client in the middle of an answer loses it. deploy.sh used to
restart the proxy on every release — of the 40 releases up to 1.3.434, 7
changed code the proxy runs, so 33 cut the agents off for nothing.

The answer comes from what the proxy says it runs: the commit it started from
and its pid, written into its state file when it starts
(caravan/proxy/started.py). Not from the checkout's head before the pull: a
deploy with --no-restart moves the checkout and leaves the proxy behind, and
the next deploy would compare the wrong two commits and keep a proxy whose
code nobody can see. Whatever the record cannot vouch for restarts the proxy,
and the answer says why.

    python3 scripts/proxy_restart.py decide --new COMMIT < facts
    python3 scripts/proxy_restart.py verify [--new COMMIT] < facts

`facts` are three lines gathered on the controller by deploy.sh: what
`systemctl --user is-active` says of the proxy unit, its MainPID, and the
proxy's start record as JSON. `decide` prints "restart: why" or "keep: why".
`verify` checks the running proxy after the restart (or after leaving it
alone): it is up, the record is its own and, with --new, it runs that commit.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ProxyFacts:
    """What the controller said about the proxy: unit state, MainPID, start record."""

    def __init__(self, active="", main_pid=0, commit="", pid=0):
        self.active = str(active or "").strip()
        self.main_pid = self._number(main_pid)
        self.commit = str(commit or "").strip()
        self.pid = self._number(pid)

    @staticmethod
    def _number(value):
        try:
            return max(0, int(str(value).strip()))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def parse(cls, text):
        """Three lines as deploy.sh gathers them; whatever is missing stays unknown."""
        lines = (text or "").splitlines() + ["", "", ""]
        try:
            record = json.loads(lines[2])
        except ValueError:
            record = {}
        if not isinstance(record, dict):
            record = {}
        return cls(lines[0], lines[1], record.get("sourceCommit"), record.get("pid"))


class ProxyRestart:
    """The decision itself, by value: the facts and the files that changed, no I/O."""

    # The code the proxy process runs: its launcher and the two packages it
    # imports. scripts/check_proxy_sources.py walks the proxy's imports and
    # fails when this list no longer covers them.
    SOURCES = ("agent-proxies.py", "caravan/proxy/", "caravan/common/")
    # The proxy runs it — it is the package's own __init__ — but it holds only
    # the release number, which the proxy never reads. Every release bumps it;
    # counting it would restart the proxy on every deploy again.
    # check_proxy_sources.py guards both halves of that sentence.
    RELEASE_FILE = "caravan/__init__.py"

    def __init__(self, facts, changed):
        """`changed` — the files that differ between the running commit and the new
        one, or None when git could not tell (a commit this repository lacks)."""
        self.facts = facts
        self.changed = changed

    @classmethod
    def covers(cls, path):
        """Whether a repository path is code the proxy runs."""
        return any(path == source or (source.endswith("/") and path.startswith(source))
                   for source in cls.SOURCES)

    def verdict(self):
        """("restart" | "keep", why) — the reason is printed by the deploy as it is."""
        facts = self.facts
        if facts.active != "active":
            return "restart", f"the proxy is not running ({facts.active or 'no answer'})"
        if not facts.commit:
            return "restart", "the proxy does not say which commit it runs"
        if not facts.main_pid or facts.pid != facts.main_pid:
            return "restart", (f"the start record is not the running process's "
                               f"(record pid {facts.pid}, running pid {facts.main_pid})")
        running = facts.commit[:8]
        if self.changed is None:
            return "restart", f"the running commit {running} is not in this repository"
        touched = [path for path in self.changed if self.covers(path)]
        if touched:
            more = f" and {len(touched) - 3} more" if len(touched) > 3 else ""
            return "restart", f"proxy code changed since {running}: {', '.join(touched[:3])}{more}"
        return "keep", f"no proxy code changed since {running}"

    @staticmethod
    def same_commit(one, other):
        """The same commit abbreviated by two repositories: one a prefix of the other."""
        return bool(one) and bool(other) and (one.startswith(other) or other.startswith(one))

    def verify(self, new_commit=""):
        """("ok" | "mismatch", what) for the proxy running after the deploy."""
        facts = self.facts
        if facts.active != "active":
            return "mismatch", f"the proxy is not running ({facts.active or 'no answer'})"
        if not facts.main_pid or facts.pid != facts.main_pid:
            return "mismatch", (f"the start record is not the running process's "
                                f"(record pid {facts.pid}, running pid {facts.main_pid})")
        if new_commit and not self.same_commit(facts.commit, new_commit):
            return "mismatch", f"the proxy runs {facts.commit[:8] or '?'}, not {new_commit[:8]}"
        return "ok", f"the proxy runs {facts.commit[:8] or '?'} (pid {facts.pid})"


def changed_files(running, new, repo=ROOT):
    """Files that differ between two commits, or None when git cannot tell.

    `--no-renames`: a file moved out of the proxy's packages must count on the
    side it left, and a rename shows only its new name otherwise.
    """
    if not running or not new:
        return None
    diff = subprocess.run(["git", "diff", "--name-only", "--no-renames", running, new],
                          cwd=repo, capture_output=True, text=True)
    if diff.returncode != 0:
        return None
    return [line.strip() for line in diff.stdout.splitlines() if line.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Does this deploy restart the proxy?")
    parser.add_argument("mode", choices=("decide", "verify"))
    parser.add_argument("--new", default="", help="the commit being deployed")
    parser.add_argument("--repo", default=str(ROOT), help="the repository to diff in")
    args = parser.parse_args(argv)
    if args.mode == "decide" and not args.new:
        parser.error("decide needs --new: the commit being deployed")
    facts = ProxyFacts.parse(sys.stdin.read())
    if args.mode == "decide":
        changed = changed_files(facts.commit, args.new, Path(args.repo))
        action, why = ProxyRestart(facts, changed).verdict()
        print(f"{action}: {why}")
        return 0
    state, what = ProxyRestart(facts, []).verify(args.new)
    print(f"{state}: {what}")
    return 0 if state == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
