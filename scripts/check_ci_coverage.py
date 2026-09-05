#!/usr/bin/env python3
"""Гвард: каждый гвард и снимок из scripts/ действительно запускается — в CI и при деплое.

CI перечисляет скрипты поимённо, поэтому новый файл попадает туда только руками
— и за одну сессию про это забыли ЧЕТЫРЕ раза подряд. Тест, которого нет в
гейте, не защищает ничего: он зелёный на машине автора и не запускается больше
нигде, а выглядит как покрытие.

Падает тремя способами: файл на диске не назван в CI; в CI назван файл, которого
нет на диске (переименовали, а гейт остался звать старый); и когда список того,
что надо охранять, схлопнулся — тогда охранять нечего.

Запуск: python3 scripts/check_ci_coverage.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / ".github" / "workflows" / "ci.yml"
# Запускаются не сами по себе, а изнутри другого шага.
EXEMPT = {
    "test_guards_fail.py",   # сам вызывает все гварды
    "testability_names.py",  # вызывается с --check из шага разметки
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
# Гейт деплоя перебирает диск глобом — именно потому, что рукописный список
# там устарел: 25 имён при 38 скриптах, тринадцать не запускались перед
# выкаткой, включая самотест всех гвардов.
#
# Первая версия этой проверки искала подстроку `for guard in check_` и легко
# обходилась: список, записанный так, как файл уже пишет пути —
# `for script in "scripts/check_a.py" "scripts/check_b.py"; do` — не совпадал
# ни с чем, а глоб `scripts/check_*.py` в комментарии рядом удовлетворял второй
# половине. Ревью показало обход, скептик воспроизвёл. Теперь РАЗБИРАЕТСЯ сам
# цикл: слова после `in` до `; do`, и среди них обязан быть глоб по scripts/, а
# литеральных scripts/<имя>.py быть не должно.
DEPLOY = ROOT / "scripts" / "deploy.sh"
if DEPLOY.exists():
    deploy_text = DEPLOY.read_text(encoding="utf-8")
    code_only = "\n".join(l for l in deploy_text.splitlines() if not l.lstrip().startswith("#"))
    loops = re.findall(r"for\s+\w+\s+in\s+(.+?);\s*do", code_only)
    gate_loops = [w for w in loops if "scripts/" in w]
    if not gate_loops:
        problems.append("scripts/deploy.sh: не нашёл цикла по scripts/ — гейт деплоя исчез или переписан")
    for words in gate_loops:
        toks = [t.strip("\"'") for t in words.split()]
        # Литерал допустим только для того, что ни один глоб не покроет:
        # testability_names.py — не test_ и не check_, и ему нужен --check.
        # А вот литеральный test_*/check_* — это и есть рукописный список,
        # подменяющий глоб; первая версия правила запрещала ЛЮБОЙ литерал и
        # краснела на чистом дереве из-за этого единственного законного.
        literal = [t for t in toks if re.fullmatch(r"scripts/(?:test|check)_[A-Za-z0-9_]+\.py", t)]
        globs = [t for t in toks if "*" in t and t.startswith("scripts/")]
        if literal:
            problems.append("scripts/deploy.sh снова перечисляет скрипты руками ("
                            + ", ".join(literal[:3]) + (", …" if len(literal) > 3 else "")
                            + ") — такой список устаревает молча")
        if not globs:
            problems.append("scripts/deploy.sh: цикл гейта без глоба по scripts/ — новые скрипты не подхватятся")

# Имя, названное в ci.yml, засчитывалось этим гвардом ЛЮБОЕ — в том числе
# написанное во втором `run:` того же шага. YAML не терпит двух одинаковых
# ключей в одном отображении: шаг либо невалиден, либо исполняет ровно один из
# них, — а гвард всё это время печатал зелёное, потому что искал подстроку.
# Ровно тот же обход, что дважды находили у других гвардов: удовлетворяется
# УПОМИНАНИЕМ, а не исполнением. Поэтому ключи шага теперь пересчитываются.
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
    if indent < cur_indent:          # вышли из шага — дальше уже не его ключи
        _close_step()
        cur_indent = None
        cur_keys = {}
        continue
    if indent == cur_indent:
        cur_keys[k.group(2)] = cur_keys.get(k.group(2), 0) + 1
if cur_indent is not None:
    _close_step()

# Считаются не «шаги», а шаги С `run:` — иначе сигнал устаревания молчит там,
# где важен: первая редакция считала любую строку вида `- слово:` за шаг, и
# переименование ключа шага её не тревожило.
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
