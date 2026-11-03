#!/usr/bin/env python3
"""The editor's command preview must agree with the command that gets run.

Two builders render a cell's launch line: the program's runners, which write start.sh, and _buildCommandExecPreview() in JS, which draws the "NEW COMMAND" pane so the
operator can read it before pressing Apply. They are separate on purpose — the preview updates on every keystroke without a round trip — and separate things drift.

They did. HUGGINGFACE_HUB_CACHE was added to the translate builder so the weights land in the models tree; the JS mirror kept showing the line without it, so the pane
promised one command and Apply wrote another. contract/runner_lines.json holds the whole lines; this checks the part that actually drifted, over every runner of the
program: every cache root a builder pins must appear verbatim in the mirror.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rust_source import RustSource  # noqa: E402

MIRROR = ROOT / "static/js/llama-edit.js"
BUILDERS = "admin/src/domain/runner"


def main():
    builders = "\n".join("\n".join(lines) for _rel, lines in RustSource.files(BUILDERS))
    js = MIRROR.read_text(encoding="utf-8")
    errors = []

    # HUGGINGFACE_HUB_CACHE=\"${{LLAMA_MODELS_DIR:-$HOME/llama-model-cache}}/<dir>\"
    roots = re.findall(r"""LLAMA_MODELS_DIR:-\$HOME/llama-model-cache\}\}/(\w+)""", builders)
    if not roots:
        errors.append(f"no HUGGINGFACE_HUB_CACHE roots found in rust/crates/{BUILDERS} — check this pattern")
    for root in roots:
        needle = f'llama-model-cache}}/{root}"'
        if needle not in js:
            errors.append(
                f"the program's builder pins the {root} cache under the models tree, but the\n"
                f"        preview in llama-edit.js does not mention it. The pane would show a\n"
                f"        command that differs from the one Apply writes.")

    # The safetensors format list is mirrored into the board's JS so a card can read <Model>/<author>/<FORMAT> without a round trip. It drifted: the mirror carried "ST",
    # which is the badge the program shows when it recognises NO format, never a directory. A folder named ST would have been stripped by the browser and kept by the
    # program, so the two disagreed about the model's own name.
    board = (ROOT / "static/js/topology-nodes.js").read_text(encoding="utf-8")
    js_hints = re.search(r"_ST_FMT\s*=\s*new Set\(\[([^\]]*)\]\)", board)
    program_set = set(RustSource.words("admin/src/models/checkpoints.rs", "FORMAT_HINTS"))
    if not js_hints:
        errors.append("не найден список форматов safetensors — проверьте этот шаблон")
    else:
        js_set = set(re.findall(r'"([^"]+)"', js_hints.group(1)))
        if program_set != js_set:
            only_program = sorted(program_set - js_set)
            only_js = sorted(js_set - program_set)
            errors.append(
                "списки форматов safetensors разошлись: "
                + (f"только в программе {only_program} " if only_program else "")
                + (f"только в JS {only_js}" if only_js else ""))

    if errors:
        print("command mirrors: FAILED", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"command mirrors OK: {len(roots)} pinned cache roots present in the preview")
    return 0


if __name__ == "__main__":
    sys.exit(main())
