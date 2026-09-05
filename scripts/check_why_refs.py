#!/usr/bin/env python3
"""Every rule in docs/why.md still points at real code.

The file exists because a rewrite loses reasons before it loses behaviour: the
function becomes a method, the method moves, and the comment explaining why the
thing was done that way is left behind. docs/why.md carries the reasons and a
reference to where each one lives — and a reference is only worth something
while it resolves.

So this checks them. During the rewrite it is the thing that says, file by file,
which rules have not been rehoused yet: move the code, this goes red, and the
red line names the rule you are about to strand.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs/why.md"

# `path/to/file.py:123` or `path/to/file.py` in backticks.
REF = re.compile(r'`([a-z][a-zA-Z0-9_/.*-]+\.(?:py|js|md|sh))(?::(\d+))?`')


def main():
    if not DOC.is_file():
        print("why refs: FAILED — docs/why.md отсутствует", file=sys.stderr)
        return 1
    text = DOC.read_text(encoding="utf-8")
    refs = REF.findall(text)
    errors = []
    for path, line in refs:
        if "*" in path:                      # a glob like cells/*_server.py
            if not list(ROOT.glob(path)):
                errors.append(f"{path} — ни одного файла по этому образцу")
            continue
        target = ROOT / path
        if not target.is_file():
            errors.append(f"{path} — файла нет; правило осиротело")
            continue
        if line:
            count = len(target.read_text(encoding="utf-8", errors="replace").splitlines())
            if int(line) > count:
                errors.append(f"{path}:{line} — в файле {count} строк; ссылка уехала")

    if errors:
        print("why refs: FAILED", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        print("\n  Код переехал — перенесите правило в docstring нового места\n"
              "  и обновите ссылку здесь. Осиротевшее правило и есть\n"
              "  потерянный инцидент.", file=sys.stderr)
        return 1
    print(f"why refs OK: {len(refs)} ссылок разрешаются")
    return 0


if __name__ == "__main__":
    sys.exit(main())
