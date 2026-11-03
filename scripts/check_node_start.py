#!/usr/bin/env python3
"""Every node a test or a guard starts is started through scripts/_node.py.

Node could hang for good inside process.exit (2026-10-21): the heaviest pin of test_js_river.py hung in about one run of
its pins in six, after it had printed its answer, until node was given --single-threaded (scripts/_node.py says why). That
flag is said once, in `NODE_FLAGS`, and given by `node_args` and `probe_args`. Until then 68 places in 67 scripts built
their own command line, so a flag added to one of them was missing from the 67 others; a command line built anywhere
else starts a node without it again.

What fails:
- a list or a tuple in scripts/*.py that begins with node itself — a name bound to find_node() or to shutil.which("node"),
  such a call, or the word "node": the command line is built by node_args or probe_args;
- shutil.which("node") outside _node.py: node is found by find_node, which also looks where nvm and fnm put it;
- the stub loader's hook (a data: URL that calls register) written outside _node.py: probe_args writes it;
- _node.py itself without --single-threaded in NODE_FLAGS, or a node_args or probe_args that does not put NODE_FLAGS
  right after the path.

Negative self-test: scripts/test_guards_fail.py.

Run: python3 scripts/check_node_start.py
"""
import ast
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class NodeStarts:
    """Every place in scripts/ that starts node, and whether it goes through scripts/_node.py."""

    HOME = "_node.py"
    #: The flag the measured hang asked for (scripts/_node.py, NODE_FLAGS).
    FLAG = "--single-threaded"
    #: A data: URL that loads a module and calls register(): the stub loader's hook, which probe_args writes.
    HOOK = re.compile(r"data:text/javascript,.*register\(")
    STARTERS = ("node_args", "probe_args")
    #: The path given to the starters when _node.py is checked: any path will do.
    SAMPLE = "/opt/node/bin/node"

    def __init__(self, root: Path = ROOT):
        self.root = root

    def scripts(self):
        for path in sorted((self.root / "scripts").glob("*.py")):
            if path.name != self.HOME:
                yield path

    @staticmethod
    def finds_node(call) -> bool:
        """A call that finds node: find_node() or shutil.which("node")."""
        name = ast.unparse(call.func)
        return name == "find_node" or (name == "shutil.which" and any(
            isinstance(a, ast.Constant) and a.value == "node" for a in call.args))

    @classmethod
    def node_names(cls, tree) -> set:
        """Names bound to a found node. A name `node` is also a graph's node in other scripts: only a binding says which."""
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and cls.finds_node(n.value):
                names |= {t.id for t in n.targets if isinstance(t, ast.Name)}
        return names

    @classmethod
    def problems_in(cls, rel: str, src: str):
        """Every place of one script that starts node by hand, as (line, what is wrong)."""
        tree = ast.parse(src)
        names = cls.node_names(tree)
        bad = {}
        for n in ast.walk(tree):
            if isinstance(n, (ast.List, ast.Tuple)) and n.elts:
                first = n.elts[0]
                if (isinstance(first, ast.Name) and first.id in names) or (isinstance(first, ast.Call) and cls.finds_node(first)) \
                        or (isinstance(first, ast.Constant) and first.value == "node"):
                    bad[n.lineno] = (f"командная строка node собрана руками — её собирает node_args или probe_args "
                                     f"(scripts/_node.py): {ast.unparse(n)[:90]}")
            elif isinstance(n, ast.Call) and ast.unparse(n.func) == "shutil.which" and cls.finds_node(n):
                bad.setdefault(n.lineno, "node найден через shutil.which — его находит find_node (scripts/_node.py), "
                                         "который видит и node из nvm и fnm")
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and cls.HOOK.search(n.value):
                bad.setdefault(n.lineno, "хук загрузчика заглушек написан руками — его пишет probe_args (scripts/_node.py)")
        return sorted(bad.items())

    def home_problems(self):
        """What _node.py must hold: the flag in NODE_FLAGS, and both starters putting NODE_FLAGS right after the path."""
        path = self.root / "scripts" / self.HOME
        spec = importlib.util.spec_from_file_location("_node_under_check", path)
        home = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(home)
        flags = tuple(getattr(home, "NODE_FLAGS", ()))
        bad = []
        if self.FLAG not in flags:
            bad.append(f"scripts/{self.HOME}: в NODE_FLAGS нет {self.FLAG} — node снова может зависнуть в process.exit "
                       f"(почему — там же, над NODE_FLAGS)")
        head = [self.SAMPLE, *flags]
        if home.node_args(self.SAMPLE, "a")[:len(head)] != head:
            bad.append(f"scripts/{self.HOME}: node_args не ставит NODE_FLAGS сразу за путём к node")
        if home.probe_args(self.SAMPLE, self.root / "scripts" / "_js_harness.mjs", "p")[:len(head)] != head:
            bad.append(f"scripts/{self.HOME}: probe_args не ставит NODE_FLAGS сразу за путём к node")
        return bad

    def problems(self):
        bad, starts = self.home_problems(), 0
        for path in self.scripts():
            src = path.read_text(encoding="utf-8")
            rel = path.relative_to(self.root).as_posix()
            bad += [f"{rel}:{line}: {what}" for line, what in self.problems_in(rel, src)]
            starts += sum(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in self.STARTERS
                          for n in ast.walk(ast.parse(src)))
        return bad, starts


def main():
    bad, starts = NodeStarts().problems()
    if bad:
        print("node start: FAILED", file=sys.stderr)
        for line in bad:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print(f"node start OK: {starts} мест запускают node, и все — через scripts/_node.py ({NodeStarts.FLAG})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
