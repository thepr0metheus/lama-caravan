#!/usr/bin/env python3
"""The editor's command preview must agree with the command that gets run.

Two builders render a cell's launch line: build_*_command() in Python, which
writes start.sh, and _buildCommandExecPreview() in JS, which draws the "NEW
COMMAND" pane so the operator can read it before pressing Apply. They are
separate on purpose — the preview updates on every keystroke without a round
trip — and separate things drift.

They did. HUGGINGFACE_HUB_CACHE was added to the Python translate builder so
the weights land in the models tree; the JS mirror kept showing the line
without it, so the pane promised one command and Apply wrote another.

A full comparison would mean running the JS, so this checks the part that
actually drifted and matters: every cache root the Python builders pin must
appear verbatim in the mirror.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MIRROR = ROOT / "static/js/llama-edit.js"
BUILDERS = ROOT / "caravan/admin/runners.py"

CACHE_RE = re.compile(r'HUGGINGFACE_HUB_CACHE=\{?cache\}?|/(\w+)"\'\s*$')


def main():
    py = BUILDERS.read_text(encoding="utf-8")
    js = MIRROR.read_text(encoding="utf-8")
    errors = []

    # cache = '"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/<dir>"'
    roots = re.findall(r"""cache\s*=\s*'"\$\{LLAMA_MODELS_DIR:-\$HOME/llama-model-cache\}/(\w+)"'""", py)
    if not roots:
        errors.append("no HUGGINGFACE_HUB_CACHE roots found in runners.py — check this pattern")
    for root in roots:
        needle = f'llama-model-cache}}/{root}"'
        if needle not in js:
            errors.append(
                f"the Python builder pins the {root} cache under the models tree, but the\n"
                f"        preview in llama-edit.js does not mention it. The pane would show a\n"
                f"        command that differs from the one Apply writes.")

    if errors:
        print("command mirrors: FAILED", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"command mirrors OK: {len(roots)} pinned cache roots present in the preview")
    return 0


if __name__ == "__main__":
    sys.exit(main())
