#!/usr/bin/env python3
"""A 401 from the board means one thing: the board's own sign-in.

The board's `api()` answers any 401 by sending the page to /login — that is
how an expired session gets the operator back to the form. So a 401 that
means anything else logs the operator out. The subscription usage call
raised one when chatgpt.com refused its OAuth token (2026-09-27): an expired
ChatGPT sign-in threw the operator off the board, up to three times, until
the breaker tripped. A provider's refusal is an upstream failure — 502, with
words that say whose sign-in it is.

This reads caravan/admin for every AppError(..., 401) and send_json(..., 401)
and lets through only the board's own answers, named below by their words.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADMIN = ROOT / "caravan" / "admin"

#: The board's own sign-in answers — the only 401s it may give.
ALLOWED = (
    "invalid username or password",          # the login form refusing a password
    "authentication required",               # no session on an API call
    "fleet token required",                  # a scout without the fleet token
)


def _status_401(call):
    args = call.args
    if len(args) >= 2 and isinstance(args[1], ast.Constant) and args[1].value == 401:
        return True
    return any(k.arg in ("status", "code") and isinstance(k.value, ast.Constant) and k.value.value == 401
               for k in call.keywords)


def _is_answer(call):
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    return name in ("AppError", "send_json")


def offenders(source, rel):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_answer(node) and _status_401(node):
            text = ast.get_source_segment(source, node) or ""
            if not any(words in text for words in ALLOWED):
                yield f"{rel}:{node.lineno}: {text.strip()[:120]}"


def main():
    files = sorted(ADMIN.glob("*.py"))
    if not files:
        print("board 401: FAILED — в caravan/admin нет ни одного .py", file=sys.stderr)
        return 1
    errors = []
    for path in files:
        errors.extend(offenders(path.read_text(encoding="utf-8"), path.relative_to(ROOT)))
    if errors:
        print("board 401: FAILED — 401 доски значит «войдите в доску», и страница уходит на /login:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        print("  отказ провайдера — это 502 со словами, чей вход истёк", file=sys.stderr)
        return 1
    print(f"board 401 OK: {len(files)} модулей, 401 — только вход в саму доску")
    return 0


if __name__ == "__main__":
    sys.exit(main())
