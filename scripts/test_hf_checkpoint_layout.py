#!/usr/bin/env python3
"""Value snapshot: where a safetensors repository lies on the models disk — one rule, two copies.

The /hf page decides where each file of a checkpoint lands (static/js/hf-downloads.js:
checkpointDir, checkpointFileDir) and sends the server each file's `destDir`. The
check of such a repository (caravan/admin/hf_checkpoint.py: CheckpointLayout) has to
look in exactly those places, so the rule lives twice, in the browser and on the
server. Both copies are run here against ONE table of cases: the copy that drifts
turns this red, instead of a check that says "missing" about a folder that is whole.

The table holds what the page does with a repository's own folders (GR00T's
experiment_cfg/ keeps its place), with a file at the top, with "." and ".." steps
(they never lead out of the folder), with a repository that names no author, and
with a label the page chose for the folder.

The folder the GGUF scan reads (<model>/<author>/, caravan/admin/hf.py) is the
folder the checkpoint check reads: a third place that has to agree.

Run: python3 scripts/test_hf_checkpoint_layout.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _js_pins import run  # noqa: E402
from caravan.admin.hf_checkpoint import CheckpointLayout  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# (repo id, the label the page gave the folder, the file's path in the repository, its name,
#  where it lies below the models directory, what the case is for)
CASES = [
    ("nvidia/GR00T-N1.7-3B", "BF16", "model-00001-of-00002.safetensors", "model-00001-of-00002.safetensors",
     "GR00T-N1.7-3B/nvidia/BF16/model-00001-of-00002.safetensors", "a file at the top lies in the folder of the checkpoint"),
    ("nvidia/GR00T-N1.7-3B", "BF16", "experiment_cfg/conf.yaml", "conf.yaml",
     "GR00T-N1.7-3B/nvidia/BF16/experiment_cfg/conf.yaml", "defect-history: a file keeps its folder of the repository (the runtime reads experiment_cfg/)"),
    ("nvidia/GR00T-N1.7-3B", "BF16", "a/b/c/deep.json", "deep.json",
     "GR00T-N1.7-3B/nvidia/BF16/a/b/c/deep.json", "folders of any depth are kept"),
    ("org/m", "FP8", "a/../b/./c.json", "c.json",
     "m/org/FP8/a/b/c.json", "\".\" and \"..\" steps are dropped, not followed"),
    ("org/m", "FP8", "../../up.json", "up.json",
     "m/org/FP8/up.json", "negative: a path of \"..\" steps does not lead out of the folder"),
    ("org/m", "FP8", "a//b.json", "b.json", "m/org/FP8/a/b.json", "an empty step is dropped"),
    ("solo", "safetensors", "x/w.safetensors", "w.safetensors",
     "solo/unknown/safetensors/x/w.safetensors", "a repository that names no author lies under \"unknown\""),
    ("a/b/c", "BF16", "f.json", "f.json", "c/a/BF16/f.json", "the model is the LAST part of the id, the author the first"),
    ("nvidia/Cosmos-Reason2-2B", "SAFETENSORS", "tokenizer.json", "tokenizer.json",
     "Cosmos-Reason2-2B/nvidia/SAFETENSORS/tokenizer.json", "the label is whatever the page gave: a different label is a different folder"),
]

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const D = await import(pathToFileURL(process.env.JS_ROOT + "/hf-downloads.js").href);
const reset = () => {};
const CASES = %s;
"""

JS_RULE = r"""CASES.map(([repo, label, path, name]) => `${D.HfDownloads.checkpointFileDir(D.HfDownloads.checkpointDir(repo, label), path)}/${name}`)"""


def python_rule(repo, label, path, name):
    return f"{CheckpointLayout.repo_folder(repo)}/{label}/{CheckpointLayout.file_path(path, name)}"


def main():
    print("the server's copy:")
    for repo, label, path, name, want, why in CASES:
        got = python_rule(repo, label, path, name)
        check(got == want, f"{why} (got {got!r})")

    print("the folder the GGUF scan reads:")
    import caravan.admin.hf as hf
    import caravan.admin.model_locator as locator
    with tempfile.TemporaryDirectory() as tmp:
        models = Path(tmp)
        repo = "bartowski/gemma-4-12B-it-GGUF"
        target = models / CheckpointLayout.repo_folder(repo) / "Q4_K_M" / "gemma-Q4_K_M.gguf"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"x")
        real = (hf.models_dir_from_config, hf.parse_config, locator.current_locations)
        hf.models_dir_from_config = lambda _cfg: models
        hf.parse_config = lambda: {}
        locator.current_locations = lambda wait=False: locator.Locations([])
        try:
            found = hf.hf_local_check(repo)
        finally:
            hf.models_dir_from_config, hf.parse_config, locator.current_locations = real
        check(found.get("localNames") == ["gemma-Q4_K_M.gguf"],
              f"a GGUF placed under repo_folder() is found by the GGUF scan: both read <model>/<author>/ (got {found.get('localNames')})")

    print("the browser's copy:")
    pin = ("layout_twin", "", JS_RULE, json.dumps([c[4] for c in CASES]),
           "the browser lays every case of the table out exactly where the server's copy looks")
    code = run("js hf-downloads layout", ".probe_hf_checkpoint_layout.tmp.mjs",
               PREAMBLE % json.dumps([list(c[:4]) for c in CASES]), [pin])

    if _fail or code:
        print(f"FAILED ({len(_fail)} here, js exit {code}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("hf checkpoint layout snapshots hold")


if __name__ == "__main__":
    main()
