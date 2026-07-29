#!/usr/bin/env python3
"""Every `data-t` value the UI can emit — the list docs/testability.md publishes.

WHY THIS IS NOT A GREP. Most hooks are literals in the markup and a grep finds
them. Some are composed at runtime and a grep finds NOTHING:

    trigger.dataset.t = `${selectEl.dataset.t}-picker`   → cell-edit-model-picker
    `data-t="${tHook}"`                                  → cell-edit-runner-tab
    mbadge(type, text, title, "cell-source-stale")       → cell-source-stale

Counting only the literals undercounts by eleven, and a reader who greps, gets a
smaller number than the doc, and concludes the doc has drifted will "fix" it in
the wrong direction. So the composed names are declared here, next to the rule
that composes them, and the doc's count comes from this script.

    python3 scripts/testability_names.py            # the list
    python3 scripts/testability_names.py --check    # non-zero if the doc disagrees
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = ("static", "caravan")

# Hooks assembled at runtime, with the site that assembles each. Add here when
# you add one — the guard below is what will otherwise catch you.
COMPOSED = {
    # static/js/form.js — the visible widget above a hidden native <select>
    "cell-edit-model-picker": "form.js: `${selectEl.dataset.t}-picker`",
    "cell-edit-vllm-model-picker": "form.js: `${selectEl.dataset.t}-picker`",
    "cell-edit-whisper-model-picker": "form.js: `${selectEl.dataset.t}-picker`",
    "cell-edit-moonshine-model-picker": "form.js: `${selectEl.dataset.t}-picker`",
    "cell-remote-model-picker": "form.js: `${selectEl.dataset.t}-picker`",
    "cell-remote-vllm-model-picker": "form.js: `${selectEl.dataset.t}-picker`",
    "cell-remote-whisper-model-picker": "form.js: `${selectEl.dataset.t}-picker`",
    "cell-remote-moonshine-model-picker": "form.js: `${selectEl.dataset.t}-picker`",
    # static/js/llama-edit.js — one per runner, carrying data-t-id
    "cell-edit-runner-tab": "llama-edit.js: tHook by prefix",
    "cell-remote-runner-tab": "llama-edit.js: tHook by prefix",
    # static/js/topology-nodes.js — passed to mbadge() as its testId argument
    "cell-source-stale": "topology-nodes.js: mbadge(..., 'cell-source-stale')",
}

LITERAL = re.compile(r'data-t="([a-z][a-z0-9-]*)"')


def names():
    out = subprocess.run(
        ["grep", "-rhoE", r'data-t="[a-z][a-z0-9-]*"', *SCAN],
        cwd=ROOT, capture_output=True, text=True).stdout
    return sorted(set(LITERAL.findall(out)) | set(COMPOSED))


def main():
    all_names = names()
    if "--check" not in sys.argv:
        for n in all_names:
            print(n)
        print(f"\n{len(all_names)} values "
              f"({len(all_names) - len(COMPOSED)} literal + {len(COMPOSED)} composed)",
              file=sys.stderr)
        return 0

    doc_path = os.path.join(ROOT, "docs", "testability.md")
    with open(doc_path, encoding="utf-8") as fh:
        doc = fh.read()
    m = re.search(r"Generated from the source, not from memory — (\d+) values", doc)
    if not m:
        print("testability.md: the generated-names header is missing", file=sys.stderr)
        return 1
    listed = set(re.findall(r'`([a-z][a-z0-9-]*)`',
                            doc.split("Generated from the source")[1]
                               .split("Repeated elements carry")[0]))
    problems = []
    if int(m.group(1)) != len(all_names):
        problems.append(f"header says {m.group(1)} values, source has {len(all_names)}")
    for n in sorted(set(all_names) - listed):
        problems.append(f"in the source but not in the doc: {n}")
    for n in sorted(listed - set(all_names)):
        problems.append(f"in the doc but no longer in the source: {n}")
    for p in problems:
        print(f"testability.md: {p}", file=sys.stderr)
    if problems:
        print("\nregenerate with: python3 scripts/testability_names.py", file=sys.stderr)
        return 1
    print(f"testability contract OK: {len(all_names)} data-t values, doc matches source")
    return 0


if __name__ == "__main__":
    sys.exit(main())
