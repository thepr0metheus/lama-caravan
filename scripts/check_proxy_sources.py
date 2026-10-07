#!/usr/bin/env python3
"""Guard: the code the proxy runs is the code the deploy thinks it runs.

scripts/deploy.sh restarts the proxy only when a file the proxy runs has
changed, and the list of those files is ProxyRestart.SOURCES in
scripts/proxy_restart.py. A list the code outgrows is how a deploy would keep
a proxy on stale code: the day the proxy imports a module outside the list, a
change there ships to the board and never reaches the proxy, and nothing says
so.

Walks every import of agent-proxies.py, at any depth and inside functions too,
with the package __init__ files Python runs on the way. Fails five ways: a
module the proxy runs lies outside SOURCES; caravan/__init__.py, left out on
purpose, holds more than its docstring and __version__; the proxy's code reads
__version__ (a release bump would then change it after all); the proxy's code
imports dynamically, which no walk can follow; the walk found neither the
proxy's entry point nor its request handler — then it is looking in the wrong
place.

Run: python3 scripts/check_proxy_sources.py
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from proxy_restart import ProxyRestart  # noqa: E402

ENTRY = ROOT / "agent-proxies.py"
MUST_REACH = ("caravan/proxy/main.py", "caravan/proxy/handler.py")
DYNAMIC = ("importlib", "__import__")


def _rel(path):
    return path.relative_to(ROOT).as_posix()


def module_files(dotted):
    """The repository files Python runs to import `dotted`: each package's
    __init__ on the way down, then the module itself."""
    parts = dotted.split(".")
    files = []
    for depth in range(1, len(parts) + 1):
        package = ROOT.joinpath(*parts[:depth])
        if (package / "__init__.py").is_file():
            files.append(package / "__init__.py")
        elif depth == len(parts) and ROOT.joinpath(*parts[:-1], parts[-1] + ".py").is_file():
            files.append(ROOT.joinpath(*parts[:-1], parts[-1] + ".py"))
    return files


def imports_of(path):
    """The caravan modules a file imports, by dotted name — top level or not."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                package = _rel(path).removesuffix(".py").split("/")[:-1]
                package = package[:len(package) - (node.level - 1)]
                base = ".".join(package + ([base] if base else []))
            found.append(base)
            # `from caravan.proxy import graph` imports the module graph too.
            found += [f"{base}.{alias.name}" for alias in node.names]
    return [name for name in found if name == "caravan" or name.startswith("caravan.")]


def walk():
    """Every repository file the proxy process runs, from its launcher down."""
    seen, queue = set(), [ENTRY]
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        for name in imports_of(path):
            queue += [f for f in module_files(name) if f not in seen]
    return sorted(_rel(path) for path in seen)


def release_file_holds_only_the_number(path):
    """caravan/__init__.py may carry its docstring and `__version__ = "…"`, nothing else."""
    body = ast.parse(path.read_text(encoding="utf-8")).body
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    return (len(body) == 1 and isinstance(body[0], ast.Assign)
            and [getattr(t, "id", "") for t in body[0].targets] == ["__version__"]
            and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str))


def main():
    problems = []
    runs = walk()
    for must in MUST_REACH:
        if must not in runs:
            problems.append(f"обход импортов прокси не дошёл до {must} — гвард смотрит не туда")
    for rel in runs:
        if rel == ProxyRestart.RELEASE_FILE:
            if not release_file_holds_only_the_number(ROOT / rel):
                problems.append(f"{rel} держит не только номер выпуска — тогда его правка меняет код "
                                f"прокси, а выкладка прокси не перезапустит; уберите лишнее или "
                                f"исключение из ProxyRestart")
            continue
        if not ProxyRestart.covers(rel):
            problems.append(f"прокси выполняет {rel}, а его нет в ProxyRestart.SOURCES "
                            f"(scripts/proxy_restart.py) — правка там не перезапустит прокси")
            continue
        text = (ROOT / rel).read_text(encoding="utf-8")
        if "__version__" in text:
            problems.append(f"{rel} читает __version__ — тогда номер выпуска меняет поведение прокси, "
                            f"и исключение для {ProxyRestart.RELEASE_FILE} врёт")
        for word in DYNAMIC:
            if word in text:
                problems.append(f"{rel} импортирует динамически ({word}) — такой импорт обход не видит; "
                                f"назовите модуль обычным import")
    if problems:
        print("proxy sources: FAILED")
        for problem in problems:
            print("  - " + problem)
        return 1
    print(f"proxy sources OK: прокси выполняет {len(runs)} файлов, все в ProxyRestart.SOURCES "
          f"(кроме {ProxyRestart.RELEASE_FILE}: только номер выпуска)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
