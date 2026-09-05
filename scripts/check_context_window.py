#!/usr/bin/env python3
"""Гвард: опасное число не читается нигде, кроме словаря окна контекста.

`n_ctx_train` — контекст, которым модель ОБУЧЕНА, а не тот, что обслуживает
запущенный сервер. На чат-ячейке флота это 131072 против реальных 60160: вдвое
больше правды, и в ту сторону, которая заставляет клиента послать больше, чем
сервер примет. Один раз он уже был рядом с правильным числом в одном словаре
`meta`, и отличить их можно только зная, какое из них какое.

Поэтому имя разрешено только в `caravan/common/context_window.py` (где оно
названо, чтобы быть исключённым), в фикстурах снимка и в документации. Гвард
смотрит в AST, а не в текст: комментарий, объясняющий разницу, — это знание,
которое надо хранить, а не нарушение.

Падает двумя способами: когда имя появляется в коде на стороне, и когда сам
словарь перестаёт что-либо объявлять — тогда охранять уже нечего.

Запуск: python3 scripts/check_context_window.py
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOCAB = ROOT / "caravan" / "common" / "context_window.py"
FORBIDDEN = "n_ctx_train"
# Фикстуры снимка обязаны содержать обученный контекст — иначе они не смогут
# доказать, что он НЕ публикуется.
ALLOWED = {VOCAB, ROOT / "scripts" / "check_context_window.py",
           ROOT / "scripts" / "test_proxy_models.py"}
SKIP_DIRS = {"node_modules", ".git", "__pycache__", "var", "logs", "tests"}

problems = []
scanned = 0


def _walk(suffix):
    for path in ROOT.rglob(f"*{suffix}"):
        # Relative to ROOT, never the absolute path: a checkout under /private/var
        # (every temp tree the guard self-test builds) would otherwise match "var"
        # and the guard would silently examine nothing while reporting OK.
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path in ALLOWED:
            continue
        yield path


# ── 1. имя не читается в коде ────────────────────────────────────────────────
for path in _walk(".py"):
    scanned += 1
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        # An unparseable file is not a clean file. Swallowing it would let a
        # forbidden read hide behind a syntax error.
        problems.append(f"{path.relative_to(ROOT)}: не разбирается ({exc.msg}) — гвард не может его проверить")
        continue
    except Exception:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == FORBIDDEN:
            problems.append(f"{path.relative_to(ROOT)}:{node.lineno}: читает `{FORBIDDEN}` как строку")
        elif isinstance(node, ast.Attribute) and node.attr == FORBIDDEN:
            problems.append(f"{path.relative_to(ROOT)}:{node.lineno}: обращается к `.{FORBIDDEN}`")

_comment = re.compile(r"//.*$|/\*.*?\*/", re.S | re.M)
for path in _walk(".js"):
    scanned += 1
    text = _comment.sub("", path.read_text(encoding="utf-8"))
    for i, line in enumerate(text.splitlines(), 1):
        if FORBIDDEN in line:
            problems.append(f"{path.relative_to(ROOT)}:{i}: читает `{FORBIDDEN}`")

# ── 2. словарю есть что охранять ─────────────────────────────────────────────
guarded = 0
if scanned < 50:
    problems.append(f"просмотрено всего {scanned} файлов — гвард смотрит не туда, а не «всё чисто»")
if not VOCAB.exists():
    problems.append("caravan/common/context_window.py пропал — охранять нечего")
else:
    scope = {}
    exec(compile(VOCAB.read_text(encoding="utf-8"), str(VOCAB), "exec"), scope)
    for name in ("SERVED_KEYS", "SERVED_NESTED", "DECLARED_KEYS", "FORBIDDEN_KEYS"):
        value = scope.get(name)
        if not value:
            problems.append(f"context_window.{name} пуст — словарь перестал что-либо объявлять")
        else:
            guarded += len(value)
    if FORBIDDEN not in (scope.get("FORBIDDEN_KEYS") or ()):
        problems.append(f"context_window.FORBIDDEN_KEYS больше не называет `{FORBIDDEN}`")
    for fn in ("served_window", "declared_window"):
        if not callable(scope.get(fn)):
            problems.append(f"context_window.{fn} пропала — читатели остались без единого источника")

if problems:
    print("context window: FAILED")
    for p in problems:
        print("  - " + p)
    sys.exit(1)
print(f"context window OK: {scanned} файлов, `{FORBIDDEN}` нигде не читается, словарь объявляет {guarded} ключей")
