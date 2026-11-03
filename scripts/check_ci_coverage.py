#!/usr/bin/env python3
"""Guard: every guard and snapshot in scripts/ actually runs in CI.

CI lists scripts by name, so a new file only gets in there by hand — and
across one session that got forgotten FOUR times in a row. A test that isn't
in the gate protects nothing: it's green on its author's machine and never
runs anywhere else, while looking like coverage.

Fails three ways: a file on disk isn't named in CI; CI names a file that
isn't on disk (renamed, and the gate kept calling the old one); and when the
list of what to guard has collapsed to nothing — then there's nothing to guard.

Run: python3 scripts/check_ci_coverage.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / ".github" / "workflows" / "ci.yml"
# Not run on their own — called from inside another step.
EXEMPT = {
    "test_guards_fail.py",   # calls every guard itself
    "testability_names.py",  # called with --check from the tagging step
}

problems = []

if not CI.exists():
    print("ci coverage: FAILED\n  - .github/workflows/ci.yml не найден — охранять нечего")
    sys.exit(1)

ci_text = CI.read_text(encoding="utf-8")
named = set(re.findall(r"scripts/((?:test|check|testability)_[A-Za-z0-9_]+\.py)", ci_text))
on_disk = {p.name for p in ROOT.glob("scripts/*.py")
           if p.name.startswith(("test_", "check_", "testability_"))}

missing = sorted((on_disk - named) - EXEMPT)
stale = sorted(named - on_disk)

for name in missing:
    problems.append(f"scripts/{name} есть на диске, но CI его не запускает")
for name in stale:
    problems.append(f"CI зовёт scripts/{name}, которого на диске нет")
# This guard used to count ANY name mentioned in ci.yml — including one
# written into a second `run:` of the same step. YAML doesn't tolerate two
# identical keys in one mapping: the step is either invalid, or executes
# exactly one of them — while the guard kept printing green the whole time,
# because it was searching for a substring. The exact same workaround found
# twice before in other guards: satisfied by a MENTION, not by execution. So
# a step's keys are now counted.
step_re = re.compile(r"^(\s*)-\s+(\w[\w-]*):")
key_re = re.compile(r"^(\s*)([A-Za-z_][\w-]*):")
steps_with_run = 0
cur_indent = None
cur_name = ""
cur_keys = {}

def _close_step():
    global steps_with_run
    if cur_keys.get("run"):
        steps_with_run += 1
    for key, count in cur_keys.items():
        if count > 1:
            problems.append(f"ci.yml, шаг «{cur_name or '?'}»: ключ `{key}:` назван {count} раза — "
                            "YAML оставит один, второй не выполнится никогда")

for line in ci_text.splitlines():
    if not line.strip() or line.lstrip().startswith("#"):
        continue
    m = step_re.match(line)
    if m:
        if cur_indent is not None:
            _close_step()
        cur_indent = len(m.group(1)) + 2
        cur_name = line.split(":", 1)[1].strip()
        cur_keys = {m.group(2): 1}
        continue
    if cur_indent is None:
        continue
    k = key_re.match(line)
    if not k:
        continue
    indent = len(k.group(1))
    if indent < cur_indent:          # left the step — what follows isn't its keys anymore
        _close_step()
        cur_indent = None
        cur_keys = {}
        continue
    if indent == cur_indent:
        cur_keys[k.group(2)] = cur_keys.get(k.group(2), 0) + 1
if cur_indent is not None:
    _close_step()

# What's counted isn't "steps" but steps WITH `run:` — otherwise the
# staleness signal stays silent exactly where it matters: the first version
# counted any line shaped like `- word:` as a step, and renaming a step's key
# never troubled it.
if steps_with_run < 5:
    problems.append(f"в ci.yml нашлось всего {steps_with_run} шагов с `run:` — разбор шагов "
                    "сломался, дубли ключей больше не ищутся")

if len(on_disk) < 20:
    problems.append(f"найдено всего {len(on_disk)} скриптов в scripts/ — гвард смотрит не туда")
if len(named) < 20:
    problems.append(f"в ci.yml названо всего {len(named)} скриптов — разбор списка сломался")

if problems:
    print("ci coverage: FAILED")
    for p in problems:
        print("  - " + p)
    sys.exit(1)
print(f"ci coverage OK: {len(on_disk)} скриптов — все названы в CI и подхватываются глобом деплоя "
      f"({len(EXEMPT)} вызываются изнутри других)")
