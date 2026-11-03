#!/usr/bin/env python3
"""A 401 from the board means one thing: the board's own sign-in.

The board's `api()` answers any 401 by sending the page to /login — that is
how an expired session gets the operator back to the form. So a 401 that
means anything else logs the operator out. The subscription usage call
raised one when chatgpt.com refused its OAuth token (2026-09-27): an expired
ChatGPT sign-in threw the operator off the board, up to three times, until
the breaker tripped. A provider's refusal is an upstream failure — 502, with
words that say whose sign-in it is.

This reads the controller's source for every answer of 401 and lets through
only the board's own, named below by their words.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rust_source import RustSource  # noqa: E402

#: The board's own sign-in answers — the only 401s it may give.
ALLOWED = (
    "invalid username or password",          # the login form refusing a password
    "authentication required",               # no session on an API call
    "fleet token required",                  # a scout without the fleet token
)
#: The two ways an answer is said, each ending in its status.
ANSWERS = ("AppError::with_status(", ".send_json(")


def offenders(rel, lines):
    for opening in ANSWERS:
        for number, call in RustSource.calls(lines, opening):
            if re.search(r",\s*401\s*,?\s*\)$", call) and not any(words in call for words in ALLOWED) and not said_above(lines, number):
                yield f"{rel}:{number}: {call[:120]}"


def said_above(lines, number):
    """An answer that says its words through a name: `let words = if … { … } else { "authentication required" };` the line before it."""
    return number >= 2 and any(words in lines[number - 2] for words in ALLOWED)


def main():
    files = list(RustSource.files("admin/src"))
    if not files:
        print("board 401: FAILED — в rust/crates/admin/src нет ни одного файла", file=sys.stderr)
        return 1
    errors = [line for rel, lines in files for line in offenders(rel, lines)]
    if errors:
        print("board 401: FAILED — 401 доски значит «войдите в доску», и страница уходит на /login:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        print("  отказ провайдера — это 502 со словами, чей вход истёк", file=sys.stderr)
        return 1
    print(f"board 401 OK: {len(files)} файлов, 401 — только вход в саму доску")
    return 0


if __name__ == "__main__":
    sys.exit(main())
