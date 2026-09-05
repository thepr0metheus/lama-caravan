#!/usr/bin/env python3
"""A name used and never defined — the failure mode of moving code between files.

Moving a function into a class leaves its module-level constants behind, and
nothing complains: the file compiles, the import succeeds, and the NameError
waits until the one request that touches that path. moonshine's voice listing
was migrated without TTS_LOCALE and answered
`{"error": "NameError: name 'TTS_LOCALE' is not defined"}` — on production,
found by a live check, after the tests were green.

py_compile does not catch it, and the project has no linter (it runs on the
standard library, deliberately). So this is a small one, built on symtable:
for every module, collect what it defines and imports, and report any global
name it reads that is neither of those nor a builtin.

Not a type checker and not trying to be. It answers one question — "is every
name reachable?" — which is the question a rewrite keeps getting wrong.
"""
import builtins
import symtable
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__",
                                 "__package__", "__loader__", "__builtins__"}

# Names a module legitimately reads without defining: injected by a runtime, or
# defined by a star-import we cannot resolve. Each entry is a claim that the
# name arrives from somewhere real — keep it short and justified.
ALLOWED = {
    # cells/*_server.py insert their own directory on sys.path and import the
    # base by bare name; the checker sees the import, so nothing is needed here
    # today. Left in place because the next such case should be argued for, not
    # slipped in.
}


def module_undefined(path):
    """Global names this module reads but never binds."""
    source = path.read_text(encoding="utf-8")
    try:
        table = symtable.symtable(source, str(path), "exec")
    except SyntaxError as exc:
        return [f"не разбирается: {exc}"]

    defined = {s.get_name() for s in table.get_symbols()
               if s.is_assigned() or s.is_imported() or s.is_parameter()}
    # Functions and classes at module level bind their own names.
    defined |= {s.get_name() for s in table.get_symbols() if s.is_namespace()}

    missing = set()

    def walk(tbl, local):
        for sym in tbl.get_symbols():
            name = sym.get_name()
            if sym.is_global() or (not sym.is_local() and not sym.is_parameter()):
                # Dunders are the interpreter's own: __class__ inside a method
                # that uses super(), __classdict__, __conditional_annotations__
                # from deferred annotations. They are injected, never written,
                # and reporting them would bury the one name that matters.
                if (name not in defined and name not in local
                        and name not in BUILTINS and name not in ALLOWED
                        and not (name.startswith("__") and name.endswith("__"))):
                    missing.add(name)
        for child in tbl.get_children():
            inner = local | {s.get_name() for s in child.get_symbols()
                             if s.is_assigned() or s.is_parameter() or s.is_imported()}
            walk(child, inner)

    walk(table, set())
    return sorted(missing)


def main():
    # git when there is a git; a plain walk otherwise. The guard self-test runs
    # every check against a COPY of the tree, which is not a repository — a
    # checker that insisted on git would crash there and be reported as unable
    # to pass rather than as unable to fail.
    try:
        files = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.split()
    except (subprocess.CalledProcessError, FileNotFoundError):
        files = [str(p.relative_to(ROOT)) for p in sorted(ROOT.rglob("*.py"))
                 if ".git" not in p.parts and "__pycache__" not in p.parts]
    errors = []
    for rel in files:
        path = ROOT / rel
        if not path.is_file():
            continue
        for name in module_undefined(path):
            errors.append(f"{rel}: имя `{name}` используется, но нигде не определено")

    if errors:
        print("undefined names: FAILED", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        print("\n  Обычно это константа, оставшаяся в старом файле при переносе кода.",
              file=sys.stderr)
        return 1
    print(f"undefined names OK: {len(files)} модулей, ни одного недостижимого имени")
    return 0


if __name__ == "__main__":
    sys.exit(main())
