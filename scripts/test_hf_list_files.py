#!/usr/bin/env python3
"""Value snapshot: what /api/hf/files says about each file of a repository (caravan/admin/hf.py).

The listing feeds the verify of a repository, so two things about it are pinned here.

What the checkpoint plan holds. The page downloads a safetensors repository as ONE
artifact, and the check holds the folder against exactly that plan: the weights, the
configs, the tokenizer, a folder of the repository kept as a folder. Not downloaded by
design, and so never expected on disk: the README and the licence, the pictures,
.gitattributes, and the weights a second time as .bin or .pt. A file absent from the
folder that the plan does NOT hold is no finding; one that it holds is.

What the hub says about each file's bytes, entry by entry (hub_hash.py): an LFS file's
sha256, an ordinary file's git blob id, and — for a gated repository whose terms the
token has not accepted — a mask in place of the hash, which must reach the answer as
"hidden" and never as a hash (nvidia/Cosmos-Reason2-2B, 2026-10-13: the tree shows
every LFS `oid` as 64 asterisks, and the sizes stay true).

The entries are shaped as the hub sends them (type, path, size, oid, lfs{oid, size,
pointerSize}, xetHash, lastCommit, securityFileStatus); no network is touched.

Run: python3 scripts/test_hf_list_files.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

os.environ.setdefault("CARAVAN_DATA_DIR", tempfile.mkdtemp(prefix="caravan-list-files-test-"))

import caravan.admin.hf as hf  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


SHA = {n: f"{n:x}" * 64 for n in range(1, 10)}          # sha256 stand-ins: 64 hex digits
GIT = {n: f"{n:x}" * 40 for n in range(1, 10)}          # git blob ids: 40 hex digits
MASK = "*" * 64


def plain(path, size, git):
    return {"type": "file", "path": path, "size": size, "oid": git, "securityFileStatus": {"status": "unscanned"},
            "lastCommit": {"id": "c1", "title": "x", "date": "2026-10-01T00:00:00.000Z"}}


def lfs(path, size, sha, pointer=135):
    return {"type": "file", "path": path, "size": size, "oid": "e" * 40, "xetHash": "x" * 64,
            "lfs": {"oid": sha, "size": size, "pointerSize": pointer},
            "securityFileStatus": {"status": "unscanned"},
            "lastCommit": {"id": "c1", "title": "x", "date": "2026-10-02T00:00:00.000Z"}}


def folder(path):
    return {"type": "directory", "path": path, "size": 0, "oid": "f" * 40}


def listing(repo, tree, config=None):
    """hf_list_files over a hub that answers `tree`, and whose config.json is `config`."""
    real = (hf._hf_request, hf._fetch_repo_config)
    hf._hf_request = lambda path, timeout=12, all_pages=False: tree
    hf._fetch_repo_config = lambda repo_id: config
    try:
        return hf.hf_list_files(repo)
    finally:
        hf._hf_request, hf._fetch_repo_config = real


def by_path(files):
    return {f["path"]: f for f in files}


def digest(entry):
    return (entry["oid"], entry["gitOid"], entry["hashHidden"])


def main():
    robot = [
        folder("experiment_cfg"),
        plain(".gitattributes", 1578, GIT[1]), plain("README.md", 13111, GIT[2]), plain("LICENSE", 4063, GIT[3]),
        lfs("model-architecture.png", 3184280, SHA[1], 132),
        plain("config.json", 2071, GIT[4]), plain("SUCCESS", 0, GIT[5]),
        plain("experiment_cfg/conf.yaml", 31159, GIT[6]),
        lfs("experiment_cfg/initial_actions.npz", 1564431, SHA[2], 132),
        lfs("model-00001-of-00002.safetensors", 4990519232, SHA[3]),
        plain("model.safetensors.index.json", 104985, GIT[7]),
        lfs("scheduler.pt", 1263, SHA[4], 129), lfs("training_args.bin", 8259, SHA[5], 129),
    ]
    got = listing("org/Robot-3B", robot, {"dtype": "bfloat16"})
    plan = by_path((got.get("safetensors") or {}).get("files") or [])
    other = by_path(got.get("otherFiles") or [])

    print("the plan of a checkpoint:")
    check(got.get("ok") and sorted(plan) == ["SUCCESS", "config.json", "experiment_cfg/conf.yaml",
                                            "experiment_cfg/initial_actions.npz", "model-00001-of-00002.safetensors",
                                            "model.safetensors.index.json"],
          f"the weights, the configs and a folder of the repository: all of them, by their path (got {sorted(plan)})")
    check(plan["experiment_cfg/conf.yaml"]["name"] == "conf.yaml", "a file of a folder has its name and its path apart")
    check(plan["SUCCESS"]["size"] == 0, "an empty file is in the plan, as an empty file")
    check(sorted(other) == [".gitattributes", "LICENSE", "README.md", "model-architecture.png", "scheduler.pt", "training_args.bin"],
          f"not downloaded by design: the README, the licence, .gitattributes, a picture, and the weights again as .pt/.bin (got {sorted(other)})")
    check(not set(plan) & set(other), "negative: a file is in the plan or out of it, never both")
    check("experiment_cfg" not in plan and "experiment_cfg" not in other, "negative: a folder entry of the tree is not a file of either")
    check((got["safetensors"]["totalSize"], got["safetensors"]["format"]) == (4990519232 + 1564431 + 104985 + 31159 + 2071, "BF16"),
          "the plan's size is the sum of the plan's files")

    print("what the hub says about each file's bytes:")
    check(digest(plan["model-00001-of-00002.safetensors"]) == (SHA[3], "", False), "an LFS file: its sha256 in `oid`")
    check(digest(plan["config.json"]) == ("", GIT[4], False), "an ordinary file: its git blob id in `gitOid`, `oid` empty")
    check(digest(plan["SUCCESS"]) == ("", GIT[5], False), "an empty ordinary file has a git id too")
    check(digest(plan["experiment_cfg/initial_actions.npz"]) == (SHA[2], "", False), "a small LFS file is an LFS file: sha256")
    check(digest(other["scheduler.pt"]) == (SHA[4], "", False) and digest(other["README.md"]) == ("", GIT[2], False),
          "the files out of the plan say the same about their bytes")

    print("a gated repository whose terms are not accepted:")
    gated = listing("nvidia/Gated-2B", [
        plain("config.json", 1505, GIT[1]), plain("tokenizer.json", 7032403, GIT[2]),
        lfs("model.safetensors", 4877470304, MASK), lfs("chart.png", 473585, MASK, 131)])
    gplan = by_path(gated["safetensors"]["files"])
    check(digest(gplan["model.safetensors"]) == ("", "", True),
          "the mask is no hash: `oid` is empty, never 64 asterisks, and `hashHidden` says why")
    check(gplan["model.safetensors"]["size"] == 4877470304, "the size the hub gives stays true — it is what the check compares")
    check(digest(gplan["config.json"]) == ("", GIT[1], False),
          "negative: the plain files of a gated repository keep their git ids — the mask hides only the LFS hashes")
    check(digest(by_path(gated["otherFiles"])["chart.png"]) == ("", "", True), "a masked file out of the plan is hidden too")

    print("GGUF files:")
    gguf = listing("acme/Model-GGUF", [
        lfs("Model-Q4_K_M.gguf", 4_000, SHA[1]), lfs("mmproj-Model-f16.gguf", 900, MASK), lfs("Model-Q8_0.gguf", 8_000, ""),
        plain("README.md", 5, GIT[1])])
    files = by_path(gguf["files"])
    check(digest(files["Model-Q4_K_M.gguf"]) == (SHA[1], "", False) and files["Model-Q4_K_M.gguf"]["quant"] == "Q4_K_M",
          "a GGUF file keeps its `oid` (the sha256 the old verify compared) and its kind and quant")
    check(digest(files["mmproj-Model-f16.gguf"]) == ("", "", True) and files["mmproj-Model-f16.gguf"]["kind"] == "mmproj",
          "a masked GGUF hash reaches the answer as hidden: it used to arrive as 64 asterisks and read as a different file")
    check(digest(files["Model-Q8_0.gguf"]) == ("", "", False),
          "negative: an LFS file with no hash given is not called hidden — only what the hub does is named")
    check("safetensors" not in gguf and [o["name"] for o in gguf["otherFiles"]] == ["README.md"],
          "a GGUF-only repository has no checkpoint plan")

    print("the parts of a split model:")
    names = ["Split-Q8_0-00001-of-00003.gguf", "Split-Q8_0-00002-of-00003.gguf", "Split-Q8_0-00003-of-00003.gguf",
             "Split-UD-Q4_K_XL-00001-of-00002.gguf", "Split-UD-Q4_K_XL-00002-of-00002.gguf",
             "Split-BF16-00001-of-00002.gguf", "Split-BF16-00002-of-00002.gguf", "Split-Q4_K_M.gguf"]
    parts = listing("acme/Split-GGUF", [lfs(name, 10_000 * (i + 1), SHA[i + 1]) for i, name in enumerate(names)])
    quants = {}
    for f in parts["files"]:
        quants.setdefault(f["quant"], []).append(f["name"])
    check(sorted(quants) == ["BF16", "Q4_K_M", "Q4_K_XL", "Q8_0"],
          "every part of a split model reads the quant of the model: four quants, not one per part (Q8_0-00003-OF-00003 was one)")
    check(sorted(quants["Q8_0"]) == names[:3] and len(quants["Q4_K_XL"]) == 2 and len(quants["BF16"]) == 2
          and quants["Q4_K_M"] == ["Split-Q4_K_M.gguf"],
          "the parts of a model share one quant, and so one row on the page and one folder on the disk; a whole file is its own")
    got_sha = {f["name"]: f["oid"] for f in parts["files"]}
    check(got_sha == {name: SHA[i + 1] for i, name in enumerate(names)},
          "a part keeps its own sha256: the verify compares every part against the hub")

    print("the quant read off a file name — the table the page is run against too:")
    from hf_quant_cases import QUANT_CASES  # noqa: E402
    wrong = [(name, hf._extract_quant(name), quant) for name, quant in QUANT_CASES if hf._extract_quant(name) != quant]
    check(not wrong, f"every name of scripts/hf_quant_cases.py reads as the table says ({len(QUANT_CASES)} names)"
          + (f"; read otherwise: {wrong}" if wrong else ""))

    print("a repository with both kinds:")
    both = listing("acme/Both-7B", [
        lfs("Both-7B-Q4_K_M.gguf", 4_000, SHA[1]), lfs("model-00001-of-00001.safetensors", 14_000, SHA[2]),
        plain("config.json", 600, GIT[1])], {"torch_dtype": "float16"})
    check([f["name"] for f in both["files"]] == ["Both-7B-Q4_K_M.gguf"]
          and sorted(f["name"] for f in both["safetensors"]["files"]) == ["config.json", "model-00001-of-00001.safetensors"],
          "the GGUF file is a GGUF file, the weights and the config are the plan: one listing, two kinds, no file in both")

    print("no checkpoint where there are no safetensors weights:")
    onnx = listing("acme/Onnx-Only", [lfs("model.onnx", 100, SHA[1]), plain("config.json", 5, GIT[1])])
    check("safetensors" not in onnx and sorted(by_path(onnx["otherFiles"])) == ["config.json", "model.onnx"],
          "without .safetensors weights the config and the rest are the grey list, not a plan to verify")
    check(listing("bad id", [])["ok"] is False and listing("a/b", {"_error": "401"})["ok"] is False,
          "an invalid id and an unreachable hub are refusals, as they were")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("hf list-files snapshots hold")


if __name__ == "__main__":
    main()
