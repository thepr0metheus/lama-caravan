#!/usr/bin/env python3
"""Guard: a dangerous number is read nowhere except the context-window dict.

`n_ctx_train` is the context the model was TRAINED on, not the one the
running server actually serves. On a chat cell in the fleet that's 131072
against a real 60160: more than double the truth, and in the direction that
makes a client send more than the server will accept. It has sat right next
to the correct number in one `meta` dict before, and the only way to tell
them apart is knowing which is which.

So the name is allowed only in `caravan/common/context_window.py` (where it's
named specifically to be excluded, and from where the sole function
`trained_window` hands it out under its OWN name — a cell's card shows the
trained window next to the model's name as a fact about the weights, not as
a window), in snapshot fixtures, and in documentation. The guard looks at the
AST, not the text: a comment explaining the difference is knowledge worth
keeping, not a violation.

Fails two ways: when the name shows up in code elsewhere, and when the dict
itself stops declaring anything — then there's nothing left to guard.

Run: python3 scripts/check_context_window.py
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOCAB = ROOT / "caravan" / "common" / "context_window.py"
FORBIDDEN = "n_ctx_train"
# Snapshot fixtures must contain the trained context — otherwise they
# couldn't prove it's NOT being published.
ALLOWED = {VOCAB, ROOT / "scripts" / "check_context_window.py",
           ROOT / "scripts" / "test_proxy_models.py",
           ROOT / "scripts" / "test_context_window.py",
           ROOT / "scripts" / "test_route_windows.py",
           ROOT / "scripts" / "test_model_card.py"}
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


# ── 1. the name isn't read anywhere in code ────────────────────────────────
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

# ── 2. the dict still has something to guard ────────────────────────────────
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
    for fn in ("served_window", "declared_window", "trained_window"):
        if not callable(scope.get(fn)):
            problems.append(f"context_window.{fn} пропала — читатели остались без единого источника")

if problems:
    print("context window: FAILED")
    for p in problems:
        print("  - " + p)
    sys.exit(1)
print(f"context window OK: {scanned} файлов, `{FORBIDDEN}` нигде не читается, словарь объявляет {guarded} ключей")
