#!/usr/bin/env python3
"""Уборка общего клона (scripts/tidy_git.py) на выдуманном клоне: что уходит, что остаётся и почему.

Клон настоящий — git во временной папке, со своим origin: main, ветка, уже слитая в main, ветка с коммитом не в main, ветка сессии
приложения; рабочие копии всех видов — субагента (чистая, грязная, запертая), сессии приложения, посторонняя на неслитой ветке. Время и
процессы задаются: «сейчас» — параметр, папки процессов — список. Каждое правило — положительный пин и отрицательный.

Запуск: python3 scripts/test_tidy_git.py
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tidy_git import Tidy  # noqa: E402

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
       "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def git(cwd, *args):
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=ENV)
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {done.stderr}")
    return done.stdout.strip()


class Clone:
    """A made-up clone with its origin, branches and worktrees of every kind."""

    def __init__(self, tmp):
        tmp = Path(tmp).resolve()
        self.origin = tmp / "origin.git"
        git(tmp, "init", "--bare", "-b", "main", str(self.origin))
        self.main = tmp / "clone"
        git(tmp, "clone", "-q", str(self.origin), str(self.main))
        self.commit("a.txt", "first")
        git(self.main, "push", "-q", "origin", "main")
        # A branch merged into main, as GitLab merges a merge request: a merge commit.
        git(self.main, "checkout", "-q", "-b", "feat/done")
        self.commit("done.txt", "done")
        git(self.main, "checkout", "-q", "main")
        git(self.main, "merge", "-q", "--no-ff", "-m", "merge done", "feat/done")
        git(self.main, "push", "-q", "origin", "main")
        # A branch with a commit not in main, and an app session's branch on main.
        git(self.main, "branch", "feat/open", "main")
        git(self.main, "checkout", "-q", "feat/open")
        self.commit("open.txt", "open")
        git(self.main, "checkout", "-q", "main")
        git(self.main, "branch", "feat/side", "main")
        git(self.main, "checkout", "-q", "feat/side")
        self.commit("side.txt", "side")
        git(self.main, "checkout", "-q", "main")
        git(self.main, "branch", "claude/sess-old", "main")
        git(self.main, "fetch", "-q", "origin")
        self.trees = self.main / ".claude" / "worktrees"
        self.agent = self.add(self.trees / "agent-clean")
        self.dirty = self.add(self.trees / "agent-dirty")
        (self.dirty / "scratch.txt").write_text("not committed\n", encoding="utf-8")
        self.locked = self.add(self.trees / "agent-locked")
        git(self.main, "worktree", "lock", str(self.locked))
        self.session = self.add(self.trees / "sess-a")
        self.open = self.main.parent / "wt-open"
        git(self.main, "worktree", "add", "-q", str(self.open), "feat/open")

    def commit(self, name, text):
        (self.main / name).write_text(text + "\n", encoding="utf-8")
        git(self.main, "add", name)
        git(self.main, "commit", "-q", "-m", text)

    def add(self, path):
        git(self.main, "worktree", "add", "-q", "--detach", str(path), "origin/main")
        return path

    def tidy(self, hours_later=7.0, folders=(), gone=()):
        return Tidy(self.main, folders=None if folders is None else list(folders), now=time.time() + hours_later * 3600, gone=gone)

    def plan(self, **kw):
        _, verdicts = self.tidy(**kw).plan()
        return {Path(v.target).name if v.what == "worktree" else v.target: v for v in verdicts}


class Cases:
    def __init__(self):
        self.failures = []

    def check(self, cond, msg):
        print(("  ok  " if cond else " FAIL ") + msg)
        if not cond:
            self.failures.append(msg)

    def run(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ.update({k: v for k, v in ENV.items() if k.startswith(("GIT_AUTHOR", "GIT_COMMITTER", "GIT_CONFIG"))})
            clone = Clone(tmp)
            self.worktrees(clone)
            self.branches(clone)
            self.applying(clone)
        if self.failures:
            print(f"\ntidy git FAILED ({len(self.failures)}):")
            for msg in self.failures:
                print("  -", msg)
            return 1
        print("\ntidy git OK: уходит только слитое, чистое, заброшенное; остальное остаётся с причиной")
        return 0

    def worktrees(self, clone):
        print("рабочие копии:")
        plan = clone.plan()
        self.check(plan["agent-clean"].remove, f"копия субагента — чистая, в main, никого, 7 ч тишины — уходит ({plan['agent-clean'].why})")
        fresh = clone.plan(hours_later=1)
        self.check(not fresh["agent-clean"].remove and "тишины" in fresh["agent-clean"].why,
                   f"negative: та же копия, тронутая час назад, остаётся: только что начатая работа выглядит законченной ({fresh['agent-clean'].why})")
        self.check(not plan["agent-dirty"].remove and "незакоммиченных правок: 1" in plan["agent-dirty"].why,
                   f"negative: копия с незакоммиченным файлом остаётся ({plan['agent-dirty'].why})")
        self.check(not plan["agent-locked"].remove and "заперта" in plan["agent-locked"].why,
                   f"negative: запертая копия остаётся: замок ставит работающий агент ({plan['agent-locked'].why})")
        self.check(not plan["sess-a"].remove and "--gone sess-a" in plan["sess-a"].why,
                   f"negative: копия сессии приложения остаётся, пока сессия может вернуться ({plan['sess-a'].why})")
        self.check(clone.plan(gone=["sess-a"])["sess-a"].remove, "копия сессии, названной ушедшей (--gone), уходит")
        late = clone.plan(hours_later=30)
        self.check(not late["wt-open"].remove and "коммитов не в origin/main: 1" in late["wt-open"].why,
                   f"negative: копия на ветке с коммитом не в main остаётся и через сутки тишины ({late['wt-open'].why})")
        self.check(not plan["wt-open"].remove and "24 ч" in plan["wt-open"].why,
                   f"negative: посторонняя копия (не .claude/worktrees) ждёт сутки, а не 6 ч субагента ({plan['wt-open'].why})")
        self.check(not plan["clone"].remove and "основная" in plan["clone"].why, "negative: основная рабочая копия не уходит никогда")
        busy = clone.plan(folders=[str(clone.agent / "sub")])
        self.check(not busy["agent-clean"].remove and "процесс" in busy["agent-clean"].why,
                   f"negative: копия, в папке которой работает процесс, остаётся ({busy['agent-clean'].why})")
        blind = clone.plan(folders=None)
        self.check(not any(v.remove for v in blind.values() if v.what == "worktree") and "lsof" in blind["agent-clean"].why,
                   "negative: не узнать о процессах (нет lsof) — остаются все копии: неизвестно не значит свободно")

    def branches(self, clone):
        print("ветки:")
        plan = clone.plan()
        self.check(plan["feat/done"].remove, f"ветка, слитая в main и нигде не открытая, уходит ({plan['feat/done'].why})")
        self.check(not plan["feat/side"].remove and "коммитов не в origin/main: 1" in plan["feat/side"].why,
                   f"negative: ветка с коммитом не в main остаётся ({plan['feat/side'].why})")
        self.check(not plan["feat/open"].remove and "открыта в рабочей копии" in plan["feat/open"].why,
                   f"negative: ветка, открытая в остающейся копии, остаётся ({plan['feat/open'].why})")
        self.check(not plan["claude/sess-old"].remove and "сессии приложения" in plan["claude/sess-old"].why,
                   f"negative: ветка сессии приложения остаётся, пока сессия может вернуться ({plan['claude/sess-old'].why})")
        self.check(clone.plan(gone=["sess-old"])["claude/sess-old"].remove, "ветка сессии, названной ушедшей, уходит")
        self.check(not plan["main"].remove, "negative: main не уходит никогда")

    def applying(self, clone):
        print("уборка:")
        tidy = clone.tidy(gone=["sess-a"])
        main_path, verdicts = tidy.plan()
        sha = git(clone.main, "rev-parse", "feat/done")
        results = tidy.apply(verdicts)
        left = git(clone.main, "worktree", "list")
        branches = git(clone.main, "branch", "--format=%(refname:short)").split()
        self.check(all(done for _, done, _ in results) and not clone.agent.exists() and not clone.session.exists(),
                   "уходящие копии удалены, без --force")
        self.check(clone.dirty.exists() and clone.locked.exists() and clone.open.exists() and str(clone.dirty) in left,
                   "negative: грязная, запертая и неслитая копии на месте")
        self.check("feat/done" not in branches and {"feat/open", "feat/side", "claude/sess-old", "main"} <= set(branches),
                   f"ушла только слитая ветка; неслитая, ветка сессии и main на месте (ветки: {branches})")
        path = Tidy.record(main_path, results, tidy.now)
        lines = path.read_text(encoding="utf-8").splitlines()
        self.check(f"branch\tfeat/done\t{sha}" in lines and len(lines) == len(results),
                   "запись уборки: каждое удалённое с его коммитом — ветку вернёт git branch <имя> <sha>")
        git(clone.main, "branch", "feat/done", sha)
        self.check(git(clone.main, "rev-parse", "feat/done") == sha, "ветка возвращается по записанному коммиту")


if __name__ == "__main__":
    sys.exit(Cases().run())
