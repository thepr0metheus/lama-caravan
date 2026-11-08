#!/usr/bin/env python3
"""Tidy a clone that many sessions share: the local branches and the worktrees whose work is already in main (2026-11-08).

On 2026-11-08 the shared clone held 188 local branches whose commits were all in main, and 16 worktrees of which 12 were finished: four of
OpenCode, six of subagents, two of sessions the owner had deleted, with gigabytes of build folders in them. The rule (Papyrus
`gitlab-code-tidy`) says who removes what and when; this script is the safe part that any session can run, so that a tidy clone does not
depend on everybody remembering.

With --apply it removes, and without it only lists:
  - a local branch whose tip is in origin/main, that no remaining worktree has checked out, other than `main`. An app session's branch
    (`claude/<name>`) stays while its session may come back: it goes with `--gone <name>`, once the session is seen deleted or archived;
  - a worktree other than the main checkout that is clean (no change, no untracked file), whose HEAD is in origin/main, that is not locked,
    that no process works in, and that nobody has touched for the quiet hours of its kind: a subagent's (`.claude/worktrees/agent-*`) 6,
    any other 24. A worktree that has just started from main and changed nothing looks finished; only the quiet hours tell them apart.
    An app session's worktree (`.claude/worktrees/<name>`, not `agent-*`) goes only with `--gone <name>`: its session may be resumed.
It never forces. A dirty or unmerged worktree, a locked one, a branch with a commit not in main stay, each with its reason; so does what
cannot be known: with no lsof to ask whether a process works in a worktree, every worktree stays.
What it removed, with the commits, goes to var/cleanup-<day>/ of the main checkout: a branch comes back with `git branch <name> <sha>`.

Run: python3 scripts/tidy_git.py                       what would go, and what stays and why
     python3 scripts/tidy_git.py --apply               remove it
     python3 scripts/tidy_git.py --apply --gone NAME   and the worktree and branch of an app session that is gone
"""
import argparse
import datetime
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Git:
    """git in one folder: the exit code and what it printed."""

    def __init__(self, cwd):
        self.cwd = str(cwd)

    def run(self, *args):
        done = subprocess.run(["git", *args], cwd=self.cwd, capture_output=True, text=True)
        return done.returncode, (done.stdout + done.stderr).strip()

    def ok(self, *args):
        return self.run(*args)[0] == 0

    def out(self, *args):
        return self.run(*args)[1]


class Processes:
    """The folders that processes work in (their cwd), as lsof says."""

    @staticmethod
    def folders():
        """None when lsof cannot be asked: not knowing whether a process works in a worktree is not knowing that none does."""
        try:
            done = subprocess.run(["lsof", "-d", "cwd", "-F", "n"], capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            return None
        # lsof exits 1 when it could not read some processes; what it printed of the others still holds.
        if done.returncode not in (0, 1) or not done.stdout:
            return None
        return [line[1:] for line in done.stdout.splitlines() if line.startswith("n")]


@dataclass(frozen=True)
class Worktree:
    path: Path
    head: str
    branch: str     # "" for a detached HEAD
    locked: bool
    main: bool      # the clone's own checkout, the first one git lists


@dataclass(frozen=True)
class Verdict:
    """What happens to one worktree or branch, and why."""
    what: str       # "worktree" or "branch"
    target: str     # its path or its name
    sha: str
    remove: bool
    why: str


class Tidy:
    """The plan for one clone: which worktrees and branches go and which stay, each with its reason; and carrying it out."""

    #: Hours a worktree must have been left alone before it counts as finished, by who made it. A subagent works in bursts of minutes and
    #: its parent removes its worktree after the hand-back; anything else (a scratch worktree, another tool's) gets a day.
    QUIET_HOURS = {"agent": 6, "other": 24}
    SESSION_BRANCH = "claude/"
    #: Where the app and the Agent tool make their worktrees, under the main checkout.
    WORKTREES = Path(".claude") / "worktrees"

    def __init__(self, root=ROOT, folders=None, now=None, gone=()):
        self.git = Git(root)
        self.folders = folders
        self.now = time.time() if now is None else now
        self.gone = set(gone)

    def worktrees(self):
        found, current = [], {}
        for line in self.git.out("worktree", "list", "--porcelain").splitlines() + [""]:
            if not line:
                if current:
                    found.append(Worktree(Path(current["worktree"]), current.get("HEAD", ""),
                                          current.get("branch", "").removeprefix("refs/heads/"), "locked" in current, not found))
                current = {}
                continue
            key, _, value = line.partition(" ")
            current[key] = value
        return found

    def kind(self, worktree, main_path):
        """"agent", "session" or "other", by where it stands: the Agent tool's are `agent-*` in .claude/worktrees, the app's the rest there."""
        if worktree.path.parent != main_path / self.WORKTREES:
            return "other"
        return "agent" if worktree.path.name.startswith("agent-") else "session"

    def in_main(self, sha):
        return bool(sha) and self.git.ok("merge-base", "--is-ancestor", sha, "origin/main")

    def ahead(self, sha):
        return self.git.out("rev-list", "--count", f"origin/main..{sha}")

    @staticmethod
    def quiet_hours(worktree, now):
        """Hours since git last wrote the worktree's HEAD, index or log; None when they cannot be read. Read before `git status`, which
        may rewrite the index."""
        try:
            pointer = (worktree.path / ".git").read_text(encoding="utf-8").strip()
            gitdir = Path(pointer.removeprefix("gitdir: "))
            stamps = [(gitdir / name).stat().st_mtime for name in ("HEAD", "index", "logs/HEAD") if (gitdir / name).exists()]
        except OSError:
            return None
        return (now - max(stamps)) / 3600 if stamps else None

    def busy(self, worktree):
        """True when a process works in it, None when that cannot be known."""
        if self.folders is None:
            return None
        inside = str(worktree.path)
        return any(folder == inside or folder.startswith(inside + os.sep) for folder in self.folders)

    @staticmethod
    def changes(worktree):
        return [line for line in Git(worktree.path).out("status", "--porcelain").splitlines() if line.strip()]

    def worktree_verdict(self, worktree, main_path):
        keep = lambda why: Verdict("worktree", str(worktree.path), worktree.head, False, why)  # noqa: E731
        if worktree.main:
            return keep("основная рабочая копия клона")
        if not worktree.path.is_dir():
            return Verdict("worktree", str(worktree.path), worktree.head, True, "папки нет: git забудет её (worktree prune)")
        if worktree.locked:
            return keep("заперта: в ней может работать агент; снять замок вручную, когда его нет (git worktree unlock)")
        kind = self.kind(worktree, main_path)
        if kind == "session" and worktree.path.name not in self.gone:
            return keep(f"копия сессии приложения: сессия может вернуться (--gone {worktree.path.name}, когда её удалили или архивировали)")
        busy = self.busy(worktree)
        if busy is None:
            return keep("не узнать, работает ли в ней процесс (нет lsof)")
        if busy:
            return keep("в ней работает процесс")
        hours = self.quiet_hours(worktree, self.now)
        if hours is None:
            return keep("не прочитать, когда её трогали")
        quiet = self.QUIET_HOURS.get(kind)
        if quiet is not None and hours < quiet:
            return keep(f"трогали {hours:.1f} ч назад, меньше {quiet} ч тишины")
        if not self.in_main(worktree.head):
            return keep(f"коммитов не в origin/main: {self.ahead(worktree.head)}")
        changes = self.changes(worktree)
        if changes:
            return keep(f"незакоммиченных правок: {len(changes)}")
        return Verdict("worktree", str(worktree.path), worktree.head, True, f"чистая, в origin/main, никого нет, тишина {hours:.0f} ч")

    def branch_verdict(self, name, sha, checked_out):
        keep = lambda why: Verdict("branch", name, sha, False, why)  # noqa: E731
        if name == "main":
            return keep("main")
        if name in checked_out:
            return keep("открыта в рабочей копии, которая остаётся")
        if name.startswith(self.SESSION_BRANCH) and name.removeprefix(self.SESSION_BRANCH) not in self.gone:
            return keep("ветка сессии приложения: сессия может вернуться (--gone, когда её удалили или архивировали)")
        if not self.in_main(sha):
            return keep(f"коммитов не в origin/main: {self.ahead(sha)}")
        return Verdict("branch", name, sha, True, "в origin/main")

    def plan(self):
        worktrees = self.worktrees()
        main_path = worktrees[0].path
        verdicts = [self.worktree_verdict(worktree, main_path) for worktree in worktrees]
        # A branch whose worktree goes in this run is free to go with it.
        staying = {worktree.path: verdict for worktree, verdict in zip(worktrees, verdicts) if not verdict.remove}
        checked_out = {worktree.branch for worktree in worktrees if worktree.branch and worktree.path in staying}
        for line in self.git.out("for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads").splitlines():
            name, sha = line.split(" ")
            verdicts.append(self.branch_verdict(name, sha, checked_out))
        return main_path, verdicts

    def apply(self, verdicts):
        """Removes what the plan says goes, never by force, and says how each went: (verdict, done, what git answered)."""
        results = []
        for verdict in [v for v in verdicts if v.remove and v.what == "worktree"] + [v for v in verdicts if v.remove and v.what == "branch"]:
            if verdict.what == "worktree":
                if Path(verdict.target).is_dir():
                    code, said = self.git.run("worktree", "remove", verdict.target)
                else:
                    code, said = self.git.run("worktree", "prune")
            elif self.in_main(verdict.sha):   # once more, just before: main may not have moved, but the branch could have
                code, said = self.git.run("branch", "-D", verdict.target)
            else:
                code, said = 1, "ветка ушла вперёд после плана"
            results.append((verdict, code == 0, said))
        self.git.run("worktree", "prune")
        return results

    @staticmethod
    def record(main_path, results, now):
        """The removed ones, with their commits, as tab-separated lines in var/cleanup-<day>/ of the main checkout; the file's path."""
        stamp = datetime.datetime.fromtimestamp(now)
        folder = main_path / "var" / f"cleanup-{stamp:%Y-%m-%d}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"tidy-{stamp:%H%M%S}.tsv"
        path.write_text("".join(f"{v.what}\t{v.target}\t{v.sha}\n" for v, done, _ in results if done), encoding="utf-8")
        return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Remove the branches and worktrees whose work is already in origin/main.")
    parser.add_argument("--apply", action="store_true", help="remove; without it only list")
    parser.add_argument("--gone", action="append", default=[], metavar="NAME",
                        help="an app session seen deleted or archived: its worktree .claude/worktrees/NAME and branch claude/NAME may go")
    parser.add_argument("--no-fetch", action="store_true", help="do not fetch origin first")
    args = parser.parse_args(argv)
    git = Git(ROOT)
    if not args.no_fetch:
        git.run("fetch", "--prune", "origin")
    if not git.ok("rev-parse", "--verify", "--quiet", "origin/main"):
        print("tidy_git: нет origin/main — не с чем сверять, ничего не трогаю")
        return 2
    tidy = Tidy(ROOT, folders=Processes.folders(), gone=args.gone)
    main_path, verdicts = tidy.plan()
    going = [v for v in verdicts if v.remove]
    staying = [v for v in verdicts if not v.remove]
    print(f"останется ({len(staying)}):")
    for v in staying:
        print(f"  {v.what} {v.target}: {v.why}")
    print(f"{'уходит' if args.apply else 'уйдёт с --apply'} ({len(going)}):")
    for v in going:
        print(f"  {v.what} {v.target} [{v.sha[:8]}]: {v.why}")
    if not args.apply or not going:
        return 0
    results = tidy.apply(verdicts)
    failed = [(v, said) for v, done, said in results if not done]
    for v, said in failed:
        print(f"  НЕ УДАЛОСЬ {v.what} {v.target}: {said}")
    print(f"удалено {len(results) - len(failed)} из {len(results)}; запись: {Tidy.record(main_path, results, tidy.now)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
