#!/usr/bin/env python3
"""Guard: the caravan never runs ufw — the firewall is the operator's.

The controller used to open and close each proxy port itself with
`sudo -n ufw allow|delete allow <port>`. That needed a sudoers rule, did
nothing at all in a container, and swallowed a refusal, so a port could stay
closed with nothing saying why. Since 1.3.436 the operator opens the proxy
range once (`ufw allow 23001:23999/tcp`) and the caravan only keeps its ports
inside it (PROXY_PORTS, caravan/admin/paths.py). A ufw call slipping back in
would bring all three problems back, quietly — hence this guard.

Walks every Python file of the controller (caravan/, app.py, agent-proxies.py)
and fails two ways: a list or tuple literal with "ufw" as an element (an argv
for run/subprocess); a string that is not a docstring and reads as a ufw
command (`ufw allow …`, `sudo ufw status`). Docstrings and comments may name
the rule — they describe it, they do not run it. It also fails when it found
nothing to walk — then it is looking in the wrong place.

Run: python3 scripts/check_firewall_untouched.py
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted([*ROOT.glob("caravan/**/*.py"), ROOT / "app.py", ROOT / "agent-proxies.py"])
MUST_SEE = ("caravan/admin/proxies_config.py", "caravan/proxy/handler.py")
COMMAND = re.compile(r"\bufw\s+(allow|deny|reject|limit|delete|insert|prepend|route|status|enable|disable|reload|reset)\b")


def docstring_nodes(tree):
    """The string constants that are docstrings — they may describe ufw."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                found.add(id(body[0].value))
    return found


def problems_in(path):
    rel = path.relative_to(ROOT).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    skip = docstring_nodes(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)) and any(
                isinstance(item, ast.Constant) and item.value == "ufw" for item in node.elts):
            found.append(f"{rel}:{node.lineno}: команда ufw списком аргументов — караван не трогает файрвол")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip \
                and COMMAND.search(node.value):
            found.append(f"{rel}:{node.lineno}: строка-команда ufw ({node.value[:40]!r}) — караван не трогает файрвол")
    return found


def main():
    seen = [path.relative_to(ROOT).as_posix() for path in FILES if path.is_file()]
    problems = [f"не найден {must} — гвард смотрит не туда" for must in MUST_SEE if must not in seen]
    for path in FILES:
        if path.is_file():
            problems += problems_in(path)
    if problems:
        print("firewall untouched: FAILED")
        for problem in problems:
            print("  - " + problem)
        print("  Файрвол — дело владельца: диапазон портов прокси открыт одним правилом "
              "(PROXY_PORTS в caravan/admin/paths.py).")
        return 1
    print(f"firewall untouched OK: {len(seen)} файлов, ни одного вызова ufw")
    return 0


if __name__ == "__main__":
    sys.exit(main())
