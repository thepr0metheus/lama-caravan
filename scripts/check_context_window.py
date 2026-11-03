#!/usr/bin/env python3
"""Guard: a dangerous number is read nowhere except the context-window reader.

`n_ctx_train` is the context the model was TRAINED on, not the one the running server actually serves. On a chat cell in the fleet that's 131072 against a real 60160: more
than double the truth, and in the direction that makes a client send more than the server will accept. It has sat right next to the correct number in one `meta` dict before,
and the only way to tell them apart is knowing which is which.

So the name is allowed only in rust/crates/admin/src/common/window.rs (from where `Windows::trained` hands it out under its OWN name — a cell's card shows the trained window
next to the model's name as a fact about the weights, not as a window), in snapshot fixtures, and in documentation. A comment explaining the difference is knowledge worth
keeping, not a violation.

Fails two ways: when the name shows up in code elsewhere, and when the reader itself stops declaring anything — then there's nothing left to guard.

Run: python3 scripts/check_context_window.py
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rust_source import RustSource  # noqa: E402

VOCAB = "rust/crates/admin/src/common/window.rs"
FORBIDDEN = "n_ctx_train"
# Snapshot fixtures must contain the trained context — otherwise they
# couldn't prove it's NOT being published.
ALLOWED = {ROOT / "scripts" / "check_context_window.py",
           # The stand's engine answers what a real llama-server answers: it says this name, it reads nothing by it.
           ROOT / "scripts" / "stand" / "fake_llama.py",
           ROOT / "scripts" / "test_stand.py"}
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

for rel, lines in RustSource.files():
    scanned += 1
    for i, line in enumerate(lines, 1):
        if FORBIDDEN in line and rel != VOCAB:
            problems.append(f"{rel}:{i}: читает `{FORBIDDEN}`")

# ── 2. the reader still has something to guard ───────────────────────
if scanned < 50:
    problems.append(f"просмотрено всего {scanned} файлов — гвард смотрит не туда")
words = (ROOT / VOCAB).read_text(encoding="utf-8") if (ROOT / VOCAB).exists() else ""
guarded = sum(f"pub fn {reader}(" in words for reader in ("served", "declared", "trained"))
if guarded != 3:
    problems.append(f"{VOCAB}: читатели окна пропали (served, declared, trained) — охранять нечего")

if problems:
    print("context window: FAILED")
    for p in problems:
        print("  - " + p)
    sys.exit(1)
print(f"context window OK: {scanned} файлов, `{FORBIDDEN}` нигде не читается, {guarded} читателя окна на месте")
