#!/usr/bin/env python3
"""Value snapshot: where a safetensors repository lies on the models disk, as the /hf page lays it out.

The /hf page decides where each file of a checkpoint lands (static/js/hf-downloads.js: checkpointDir, checkpointFileDir) and sends the server each file's `destDir`. The
check of such a repository has to look in exactly those places, so the rule lives twice, in the browser and in the program (rust/crates/admin/tests/contract.rs), and
both are held to ONE table, contract/checkpoint_layout.json: the copy that drifts turns one red, instead of a check that says "missing" about a folder that is whole.

The table holds what the page does with a repository's own folders (GR00T's experiment_cfg/ keeps its place), with a file at the top, with "." and ".." steps (they never
lead out of the folder), with a repository that names no author, and with a label the page chose for the folder.

Run: python3 scripts/test_hf_checkpoint_layout.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _contract import Contract  # noqa: E402
from _js_pins import run  # noqa: E402

# (repo id, the label the page gave the folder, the file's path in the repository, its name, where it lies below the models directory, what the case is for)
CASES = [(row["repo"], row["label"], row["path"], row["name"], row["lies"], row["why"]) for row in Contract.table("checkpoint_layout")["cases"]]

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const D = await import(pathToFileURL(process.env.JS_ROOT + "/hf-downloads.js").href);
const reset = () => {};
const CASES = %s;
"""

JS_RULE = r"""CASES.map(([repo, label, path, name]) => `${D.HfDownloads.checkpointFileDir(D.HfDownloads.checkpointDir(repo, label), path)}/${name}`)"""


def main():
    print("the browser's copy:")
    pin = ("layout_twin", "", JS_RULE, json.dumps([c[4] for c in CASES]),
           "the browser lays every case of the table out exactly where the program looks")
    code = run("js hf-downloads layout", ".probe_hf_checkpoint_layout.tmp.mjs",
               PREAMBLE % json.dumps([list(c[:4]) for c in CASES]), [pin])

    if code:
        print(f"FAILED: js exit {code}")
        sys.exit(1)
    print("hf checkpoint layout snapshots hold")


if __name__ == "__main__":
    main()
