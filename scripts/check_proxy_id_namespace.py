#!/usr/bin/env python3
"""The proxy-id namespace is a WIRE FORMAT, and it is not the controller's name.

A proxy input is identified as `skynet:proxy:<port>`. That first word looks like
a hostname and reads like one, which is exactly the trap: it is a stored
identifier, and the fleet's controller has since been given a role-based id
(`controller`) with the old machine names reserved as legacy. Everything ELSE
migrated. This namespace deliberately did not, because it is written into saved
configs — the live one holds 26 references across router inputs and graph edges,
and renaming the literal in code would orphan every one of them: the inputs would
stop matching, and the operator's cables would vanish from the board.

That decision survives only as a comment and a note. This makes it a rule.

Eighteen places build or parse the prefix by hand. They agree today; what this
prevents is the tidy-minded change that makes them agree on something new.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMESPACE = "skynet"
#: `<word>:proxy:` wherever it is built or parsed, in Python or in the browser.
PATTERN = re.compile(r'([A-Za-z][A-Za-z0-9_-]*):proxy:')
TREES = ("caravan", "static/js")


def main():
    found, errors = 0, []
    for tree in TREES:
        for path in sorted((ROOT / tree).rglob("*")):
            if path.suffix not in (".py", ".js") or "__pycache__" in path.parts:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for word in PATTERN.findall(line):
                    # `in:` and `out:` are the graph's own edge prefixes and can
                    # sit directly in front of a proxy id — they are not the
                    # namespace being checked.
                    if word in ("in", "out", "rule"):
                        continue
                    found += 1
                    if word != NAMESPACE:
                        errors.append(
                            f"{path.relative_to(ROOT)}:{lineno}: неймспейс `{word}:proxy:` "
                            f"вместо `{NAMESPACE}:proxy:` — это записанный идентификатор, "
                            f"а не имя машины; в сохранённых конфигах он уже есть, и "
                            f"переименование осиротит каждую ссылку")
    if not found:
        print(f"proxy id namespace: FAILED — ни одного `{NAMESPACE}:proxy:` не найдено; "
              f"проверка перестала что-либо проверять", file=sys.stderr)
        return 1
    if errors:
        print("proxy id namespace: FAILED", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"proxy id namespace OK: {found} мест строят и разбирают "
          f"`{NAMESPACE}:proxy:`, все согласованы")
    return 0


if __name__ == "__main__":
    sys.exit(main())
