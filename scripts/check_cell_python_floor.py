#!/usr/bin/env python3
"""A cell server must load on the oldest Python any host in the fleet has.

The macOS client runs stock Python 3.9. `moonshine_server.py` carried
`voice: str | None = None` in a signature — valid syntax everywhere, and a
TypeError the moment the `def` executes on 3.9. The module never loaded, the
port never opened, and the board said the cell "did not come up", which is what
it says for a dozen unrelated reasons.

Nothing caught it. py_compile passes: the union is a perfectly good BinOp until
something evaluates it. check_undefined_names passes: every name resolves. Only
running the file on 3.9 failed, and the fleet's 3.12 hosts never did.

So the rule is structural instead: every cell server defers its annotations with
`from __future__ import annotations`, which makes them strings that are never
evaluated, and no PEP-604 union appears anywhere an interpreter would evaluate
it eagerly — outside annotations, where the future import does not reach.

The floor is not this checker's opinion; it is what README's "Tested versions"
records, and moving it is a decision about the fleet, not a lint setting.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CELLS = ROOT / "cells"
FLOOR = (3, 9)


class Unions(ast.NodeVisitor):
    """PEP-604 unions the interpreter would evaluate on import.

    Inside an annotation they are safe once annotations are deferred; anywhere
    else — a default value, an isinstance call, a module-level assignment — they
    run, and on the floor they raise.
    """

    def __init__(self):
        self.eager = []
        self._in_annotation = 0

    def visit_arg(self, node):
        # Only the annotation, and only once. generic_visit here would walk the
        # annotation a second time with the flag cleared, and every argument
        # union would be reported as if it sat in a default value.
        self._annotated(node.annotation)

    def visit_AnnAssign(self, node):
        self._annotated(node.annotation)
        if node.value:
            self.visit(node.value)

    def visit_FunctionDef(self, node):
        self._annotated(node.returns)
        for child in ast.iter_child_nodes(node):
            if child is not node.returns:
                self.visit(child)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _annotated(self, node):
        if node is None:
            return
        self._in_annotation += 1
        self.visit(node)
        self._in_annotation -= 1

    def visit_BinOp(self, node):
        if isinstance(node.op, ast.BitOr) and not self._in_annotation:
            # A `|` between two types outside an annotation. Numbers and sets use
            # the same operator, so only flag operands that look like types.
            if self._typeish(node.left) and self._typeish(node.right):
                self.eager.append(node.lineno)
        self.generic_visit(node)

    @staticmethod
    def _typeish(node):
        if isinstance(node, ast.Constant) and node.value is None:
            return True
        if isinstance(node, ast.Name):
            return node.id in {"str", "int", "float", "bool", "bytes", "list",
                               "dict", "tuple", "set", "None"}
        return isinstance(node, ast.Subscript)


def main():
    errors = []
    files = sorted(CELLS.glob("*.py"))
    if not files:
        print("cell python floor: FAILED — в cells/ нет ни одного .py", file=sys.stderr)
        return 1
    for path in files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        deferred = any(
            isinstance(node, ast.ImportFrom) and node.module == "__future__"
            and any(alias.name == "annotations" for alias in node.names)
            for node in tree.body)
        annotated = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.AnnAssign))
            and (getattr(node, "returns", None) or getattr(node, "annotation", None)
                 or any(a.annotation for a in getattr(getattr(node, "args", None), "args", []) or []))
            for node in ast.walk(tree))
        if annotated and not deferred:
            errors.append(
                f"{path.relative_to(ROOT)}: аннотации есть, а `from __future__ import "
                f"annotations` нет — на Python {FLOOR[0]}.{FLOOR[1]} `str | None` в "
                f"сигнатуре падает при исполнении def, и ячейка не поднимается")
        finder = Unions()
        finder.visit(tree)
        for line in finder.eager:
            errors.append(
                f"{path.relative_to(ROOT)}:{line}: объединение типов через `|` вне "
                f"аннотации — отложенные аннотации сюда не достают")

    if errors:
        print("cell python floor: FAILED", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"cell python floor OK: {len(files)} серверов ячеек загрузятся "
          f"на Python {FLOOR[0]}.{FLOOR[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
