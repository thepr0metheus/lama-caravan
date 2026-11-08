#!/usr/bin/env python3
"""Every Rust test binary cargo starts goes through scripts/rust_test_runner.py.

2026-11-04: two tests of `wire` hung in a busy loop in a `cargo test` an agent had started in the background and left. libtest
only warned, cargo has no time limit, and when the run's parent was gone the binary spun two cores of a Mac for three days. The
runner gives every test binary a time limit and stops it, with everything it started, once the run that started it is gone
(scripts/test_rust_test_runner.py pins how). It works only while cargo is told to use it, from wherever cargo is started.

What fails:
- the root .cargo/config.toml does not name the runner for every target: `[target.'cfg(all())']` with
  runner = "scripts/rust_test_runner.py", as a string (cargo joins the arrays of nested configs into one command line);
- the runner is missing, not executable, or without its `#!/usr/bin/env python3` line: cargo starts it as a program;
- another cargo config in the tree, a CI file or a script names a runner of its own — a config nearer the crate, a
  CARGO_TARGET_<TRIPLE>_RUNNER or a `--config` with `runner`: a nearer or a later word wins, and the tests run bare again;
- the runner's LIMIT is no number of seconds above zero, or it is not under the timeout of the CI job: then in CI the job's
  own timeout stops the run first, and nothing says which binary hung.

Negative self-test: scripts/test_guards_fail.py.

Run: python3 scripts/check_rust_test_start.py
"""
import fnmatch
import importlib.util
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class RustTestStart:
    """Whether cargo, started anywhere in the tree, starts every test binary through the runner."""

    CONFIG = Path(".cargo") / "config.toml"
    RUNNER = "scripts/rust_test_runner.py"
    TABLE = "cfg(all())"
    SHEBANG = "#!/usr/bin/env python3"
    #: Where a command line that runs cargo can stand: CI, the scripts, the delivery. fnmatch's `*` crosses folders.
    COMMANDS = (".gitlab-ci.yml", ".github/workflows/*.yml", "scripts/*.py", "scripts/*.sh", "deploy/*.py", "deploy/*.sh",
                "Makefile", "rust/*.sh")
    #: The files that name a runner of their own to say what is forbidden: this guard and the breakages that aim at it.
    SAYS_IT = {"scripts/check_rust_test_start.py", "scripts/test_guards_fail.py"}
    #: A runner said past the root config: in the environment, or as a --config of cargo's.
    OWN_RUNNER = re.compile(r"CARGO_TARGET_[A-Z0-9_]+_RUNNER|--config[ =]['\"]?target\.[^\n'\"]*runner")
    #: Folders a walk of a copy without git leaves out: what git ignores here anyway.
    SKIP = {".git", "target", "node_modules", ".venv", "__pycache__", ".claude"}
    #: The CI job's timeout: `timeout: 30m` in .gitlab-ci.yml's default section.
    CI_TIMEOUT = re.compile(r"^default:\n(?:[ \t].*\n|\n)*?[ \t]+timeout:[ \t]*(\d+)m", re.M)

    def __init__(self, root: Path = ROOT):
        self.root = root

    def tracked(self):
        """The files of the tree as git sees them: tracked, and new ones it does not ignore. A copy with no git (the guards'
        negative self-test makes one) is walked instead, without what git would ignore anyway."""
        if (self.root / ".git").exists():
            out = subprocess.run(["git", "ls-files", "-c", "-o", "--exclude-standard"], cwd=self.root, capture_output=True,
                                 text=True, check=True).stdout.splitlines()
        else:
            out = [path.relative_to(self.root).as_posix() for path in self.root.rglob("*")
                   if not self.SKIP.intersection(path.relative_to(self.root).parts)]
        return [line for line in out if (self.root / line).is_file()]

    def config_problems(self):
        path = self.root / self.CONFIG
        if not path.is_file():
            return [f"{self.CONFIG} нет — cargo запускает тесты без предела времени и без присмотра за осиротевшим запуском"]
        try:
            config = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as error:
            return [f"{self.CONFIG} не читается как TOML: {error}"]
        runner = config.get("target", {}).get(self.TABLE, {}).get("runner")
        if runner is None:
            return [f"{self.CONFIG}: в [target.'{self.TABLE}'] нет runner — тесты идут мимо {self.RUNNER}"]
        if not isinstance(runner, str):
            return [f"{self.CONFIG}: runner задан не строкой ({runner!r}) — cargo склеивает массивы вложенных конфигов в одну "
                    f"командную строку; нужно runner = \"{self.RUNNER}\""]
        if runner != self.RUNNER:
            return [f"{self.CONFIG}: runner = {runner!r}, а должен быть \"{self.RUNNER}\""]
        return []

    def runner_problems(self):
        path = self.root / self.RUNNER
        if not path.is_file():
            return [f"{self.RUNNER} нет — cargo не сможет запустить ни один тест"]
        bad = []
        if not os.access(path, os.X_OK):
            bad.append(f"{self.RUNNER} не исполняемый — cargo запускает его как программу (chmod +x, и git хранит этот бит)")
        if path.read_text(encoding="utf-8").splitlines()[:1] != [self.SHEBANG]:
            bad.append(f"{self.RUNNER}: первая строка не «{self.SHEBANG}» — cargo запускает файл сам, без python3 впереди")
        limit = self.runner_limit(path)
        timeout = self.ci_timeout()
        if not isinstance(limit, (int, float)) or limit <= 0:
            bad.append(f"{self.RUNNER}: TestBinaryRun.LIMIT = {limit!r} — не число секунд больше нуля")
        elif timeout is not None and limit >= timeout:
            bad.append(f"{self.RUNNER}: TestBinaryRun.LIMIT = {limit:g} с не меньше таймаута задания CI ({timeout:g} с) — "
                       f"в CI запуск остановит таймаут задания, и никто не скажет, какой бинарник завис")
        return bad

    @staticmethod
    def runner_limit(path):
        spec = importlib.util.spec_from_file_location("_rust_test_runner_under_check", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(getattr(module, "TestBinaryRun", None), "LIMIT", None)

    def ci_timeout(self):
        """The CI job's timeout in seconds, or None when this tree has no GitLab CI file."""
        path = self.root / ".gitlab-ci.yml"
        if not path.is_file():
            return None
        found = self.CI_TIMEOUT.search(path.read_text(encoding="utf-8"))
        return int(found.group(1)) * 60 if found else None

    def shadow_problems(self, files):
        """Another word for the runner: a cargo config nearer a crate, or a runner set where cargo is started."""
        bad = []
        root_config = self.CONFIG.as_posix()
        for rel in files:
            parts = Path(rel).parts
            if ".cargo" in parts and rel != root_config and Path(rel).name in ("config", "config.toml"):
                if "runner" in (self.root / rel).read_text(encoding="utf-8", errors="replace"):
                    bad.append(f"{rel}: свой runner в конфиге cargo ближе к крейтам — он перебивает корневой, и тесты идут "
                               f"мимо {self.RUNNER}")
        commands = {rel for rel in files if any(fnmatch.fnmatch(rel, pattern) for pattern in self.COMMANDS)} - self.SAYS_IT
        for rel in sorted(commands):
            for number, line in enumerate((self.root / rel).read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if self.OWN_RUNNER.search(line):
                    bad.append(f"{rel}:{number}: свой runner для cargo ({line.strip()[:90]}) — он перебивает "
                               f"{self.CONFIG}, и тесты идут без предела")
        return bad

    def problems(self):
        return self.config_problems() + self.runner_problems() + self.shadow_problems(self.tracked())


def main():
    bad = RustTestStart().problems()
    if bad:
        print("rust test start: FAILED", file=sys.stderr)
        for line in bad:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print(f"rust test start OK: cargo запускает каждый тестовый бинарник через {RustTestStart.RUNNER} "
          f"(предел времени, ничего не остаётся после брошенного запуска)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
