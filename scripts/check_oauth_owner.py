#!/usr/bin/env python3
"""Rotating OAuth refresh tokens have one renewal implementation."""
import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent


class OAuthOwnerGuard:
    OWNER = "caravan/common/credential_vault.py"

    def check(self):
        owners = []
        for path in (ROOT / "caravan").rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Dict):
                    values = {k.value: v.value for k, v in zip(node.keys, node.values)
                              if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)}
                    if values.get("grant_type") == "refresh_token":
                        owners.append((path.relative_to(ROOT).as_posix(), node.lineno))
        return [] if len(owners) == 1 and owners[0][0] == self.OWNER else [
            f"OAuth renewal must live only in {self.OWNER}; found {owners}"]


if __name__ == "__main__":
    errors = OAuthOwnerGuard().check()
    print("OAuth renewal owner: " + ("FAILED: " + "; ".join(errors) if errors else "OK"))
    sys.exit(bool(errors))
