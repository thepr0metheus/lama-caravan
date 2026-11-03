#!/usr/bin/env python3
"""Value snapshot: which speculative type a draft file is for, in the browser (static/js/draft-file.js).

The program names a draft's type when it builds a command (rust/crates/admin/tests/contract.rs), and the cell editor names it in the browser: both are held to ONE
table of cases, contract/draft_file.json.

What's pinned. A sidecar by the FIRST word of its name, without case, after a hyphen, an underscore or a dot; a file in a model's `mtp/` folder is an MTP head (the
defect: the scanner offered it as the model's draft and the type rule named it draft-simple, which llama.cpp runs as a model of its own on token batches without the
hidden state an MTP head drafts from); a prefix in the name outranks the folder; a word further along the name, a folder that is not exactly `mtp` and a model that
merely says MTP are no sidecars; no path is no sidecar — "" said out loud, and draft-simple only as the type to launch with. In the browser, the type a cell's draft
gets when a model is picked or speculation is switched on (`DraftFile.cellType`): the file's own, never the family's over a sidecar.

Run: python3 scripts/test_draft_file.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _contract import Contract  # noqa: E402
from _node import find_node, node_args  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


TABLE = Contract.table("draft_file")
# (path, sidecar type, launch type, what the pin is for)
CASES = [(row["path"], row["sidecar"], row["launch"], row["why"]) for row in TABLE["cases"]]
# (draft, family type, cell type, what the pin is for) — the browser's DraftFile.cellType
CELL_TYPES = [(row["draft"], row["family"], row["cell"], row["why"]) for row in TABLE["cellTypes"]]


def section_js():
    print("двойник в браузере — та же таблица:")
    node = find_node()
    if not node:
        check(False, "node не найден — двойник не проверен")
        return
    probe = (
        'import { pathToFileURL } from "node:url";\n'
        'const { DraftFile } = await import(pathToFileURL(process.env.JS_FILE).href);\n'
        f"const paths = {json.dumps([c[0] for c in CASES])};\n"
        f"const cells = {json.dumps([[d, f] for d, f, _w, _m in CELL_TYPES])};\n"
        "const out = {\n"
        "  types: paths.map((p) => [new DraftFile(p).sidecarType, new DraftFile(p).launchType]),\n"
        "  cells: cells.map(([d, f]) => DraftFile.cellType(d, f === null ? undefined : f)),\n"
        "  absent: [new DraftFile(undefined).sidecarType, new DraftFile(null).launchType],\n"
        "};\n"
        "console.log(JSON.stringify(out));\n"
    )
    env = {**os.environ, "JS_FILE": str(ROOT / "static" / "js" / "draft-file.js")}
    run = subprocess.run(node_args(node, "--input-type=module", "-e", probe), capture_output=True, text=True,
                         env=env, timeout=60)
    if run.returncode != 0:
        check(False, f"node вышел с кодом {run.returncode}: {run.stderr.strip()[-300:]}")
        return
    js = json.loads(run.stdout.strip().splitlines()[-1])
    for (path, sidecar, launch, why), got in zip(CASES, js["types"]):
        check(got == [sidecar, launch], f"js: {why} ({path!r} → {got})")
    for (draft, family, want, why), got in zip(CELL_TYPES, js["cells"]):
        check(got == want, f"js cellType: {why} ({draft!r}, {family!r} → {got})")
    check(js["absent"] == ["", "draft-simple"], f"js absence: undefined и null — как пустой путь (got {js['absent']})")
    check(len(js["types"]) == len(CASES) and len(js["cells"]) == len(CELL_TYPES),
          "двойник ответил на каждый случай таблицы")


def main():
    section_js()
    if _fail:
        print(f"\ndraft file FAILED: {len(_fail)}")
        return 1
    print(f"\ndraft file OK: {len(CASES)} paths and {len(CELL_TYPES)} cell types, one table with the program")
    return 0


if __name__ == "__main__":
    sys.exit(main())
