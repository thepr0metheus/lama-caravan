#!/usr/bin/env python3
"""The models directory is derived in one place.

paths.rs names the default (LLAMA_MODELS_DIR, else LLAMA_HOME/models, else the data volume's models/ in a container) and `App::models_dir_of` puts the saved config over it.
A module that builds it from LLAMA_HOME itself holds a SECOND opinion about where the models are — the same place only while the config agrees with it. Two functions did:
in a container GET /api/models listed nothing and GET /api/models/download answered 404 for every file the picker had just offered.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rust_source import RustSource  # noqa: E402


class ModelsDirSourceGuard:
    OWNER = "rust/crates/admin/src/paths.rs"
    DERIVES = re.compile(r'llama_home[^;]*join\("models"\)|llama_home[^;]*/models')

    def check(self):
        seen, found = False, []
        for rel, lines in RustSource.files("admin/src"):
            hits = [number for number, line in enumerate(lines, 1) if self.DERIVES.search(line)]
            if rel == self.OWNER:
                seen = bool(hits)
            else:
                found += [f"{rel}:{number}" for number in hits]
        errors = [f"the models directory is derived in {self.OWNER} and `models_dir_of` only; {', '.join(found)} builds it from llama_home itself"] if found else []
        return errors + ([] if seen else [f"{self.OWNER} no longer derives it: this guard is looking at nothing"])


if __name__ == "__main__":
    errors = ModelsDirSourceGuard().check()
    print("models directory source: " + ("FAILED: " + "; ".join(errors) if errors else "OK"))
    sys.exit(bool(errors))
