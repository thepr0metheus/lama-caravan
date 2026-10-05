#!/usr/bin/env python3
"""The models directory is derived in one place.

paths.py names the default (LLAMA_MODELS_DIR, else LLAMA_HOME/models, else the data
volume's models/ in a container) and models_dir_from_config puts the saved config over
it. A module that builds `LLAMA_HOME / "models"` itself holds a SECOND opinion about
where the models are — the same place only while the config agrees with it. Two
functions did: in a container GET /api/models listed nothing and GET /api/models/download
answered 404 for every file the picker had just offered.
"""
import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent


class ModelsDirSourceGuard:
    OWNER = "caravan/admin/paths.py"

    @staticmethod
    def _is_home(node):
        return "LLAMA_HOME" in ast.unparse(node)

    @staticmethod
    def _is_models(node):
        return isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.strip("/") == "models"

    def derives(self, node):
        """Whether the node builds the models directory out of LLAMA_HOME: `LLAMA_HOME / "models"`,
        `os.path.join(LLAMA_HOME, "models")`, or `f"{LLAMA_HOME}/models"`."""
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return self._is_home(node.left) and self._is_models(node.right)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "join":
            return len(node.args) >= 2 and any(self._is_home(a) for a in node.args[:-1]) and self._is_models(node.args[-1])
        if isinstance(node, ast.JoinedStr):
            return self._is_home(node) and any(self._is_models(v) or (isinstance(v, ast.Constant) and "/models" in str(v.value))
                                               for v in node.values)
        return False

    def check(self):
        found = []
        for path in sorted((ROOT / "caravan").rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel == self.OWNER:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if self.derives(node):
                    found.append(f"{rel}:{node.lineno}")
        return [f"the models directory is derived in {self.OWNER} and models_dir_from_config only; "
                f"{', '.join(found)} builds it from LLAMA_HOME itself"] if found else []


if __name__ == "__main__":
    errors = ModelsDirSourceGuard().check()
    print("models directory source: " + ("FAILED: " + "; ".join(errors) if errors else "OK"))
    sys.exit(bool(errors))
