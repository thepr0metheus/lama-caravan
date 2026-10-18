#!/usr/bin/env python3
"""Value snapshot: POST /api/hf/verify on a safetensors repository — the folder the page laid out.

The verify looked for *.gguf only. Asked about nvidia/Cosmos-Reason2-2B, whose folder
(config.json, tokenizer files, model.safetensors) was whole on the models disk, it answered
"nothing of this repo is on disk" (found 2026-10-13). Now every file of the download is held
against the hub's tree, and each claim here is pinned together with its opposite.

The whole chain is run, from a hub tree and a models folder given as data: the route, the
listing (hf_list_files), the finder (hf_checkpoint.py) and the job (hf_verify.py), with no network.
The hub's answers have the shape the hub sends, including the one that made a gated repository
read as "everything differs": 64 asterisks where an LFS hash stands.

What is pinned:
* a folder with every file is verified, file by file, by the hash the hub gave (the sha256 of an LFS
  file, the git blob id of an ordinary one) — a folder of the repository keeps its place;
* a missing file, a file of the wrong size and a file with other bytes are each NAMED, as three
  different things; the wrong size is not even read;
* a file the plan does not hold (README, .gitattributes, a picture, weights again as .bin) is never
  expected, whether it is on disk or not;
* a gated repository: the files whose hash is hidden are checked by size only and the row SAYS so
  (`size-only`, hash `hidden`) — not a pass and not a failure — and the ordinary files of the same
  repository are still checked by hash;
* the folder is found by what it holds, not by the label the page would give it today (the listing of
  a gated repository says SAFETENSORS; the copy sits under BF16), every copy answers on its own, and
  a GGUF quant folder next to it is never taken for one;
* a repository with both GGUF and safetensors files answers both, each in its own section;
* nothing on disk is a refusal, and a checkpoint that was never downloaded is not "N files missing";
* a half-read copy does not read as a whole one (`pending`).

Run: python3 scripts/test_hf_verify_checkpoint.py
"""
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import types
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="caravan-verify-checkpoint-test-"))
os.environ["CARAVAN_DATA_DIR"] = str(_TMP / "data")
os.environ["LLAMA_ADMIN_STATE"] = str(_TMP / "data" / "admin.json")

import caravan.admin.hf as hf  # noqa: E402
import caravan.admin.hf_checkpoint as hc  # noqa: E402
import caravan.admin.hf_verify as hv  # noqa: E402
import caravan.admin.model_locator as locator  # noqa: E402
from caravan.admin import routes  # noqa: E402
from caravan.admin.hub_hash import HubHash  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# What a hub entry's hashes are, worked out here with hashlib alone: the pins must not lean on the
# code they pin.
def sha(data):
    return hashlib.sha256(data).hexdigest()


def git_id(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


EMPTY_GIT_ID = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"  # what `git hash-object` says of an empty file
HELLO_GIT_ID = "3b18e512dba79e4c8300dd08aeb37f8e728b8dad"  # … of b"hello world\n"
HELLO_SHA256 = "a948904f2f0f479b8f8197694b30184b0d2ed1c1cd2a1ec0fb85d299a192a447"
MASK = "*" * 64


def plain_item(path, data):
    return {"type": "file", "path": path, "size": len(data), "oid": git_id(data),
            "securityFileStatus": {"status": "unscanned"}, "lastCommit": {"id": "c1", "title": "x", "date": "2026-10-01T00:00:00.000Z"}}


def lfs_item(path, data, oid=None):
    return {"type": "file", "path": path, "size": len(data), "oid": "e" * 40, "xetHash": "x" * 64,
            "lfs": {"oid": oid if oid is not None else sha(data), "size": len(data), "pointerSize": 135},
            "securityFileStatus": {"status": "unscanned"}, "lastCommit": {"id": "c1", "title": "x", "date": "2026-10-02T00:00:00.000Z"}}


# A robot-policy-shaped checkpoint (GR00T's layout): weights, configs, an empty marker and a
# folder of the repository the runtime reads.
REPO = "acme/Robot-3B"
CONTENT = {
    "config.json": b'{"model_type": "robot"}\n',
    "SUCCESS": b"",
    "experiment_cfg/conf.yaml": b"horizon: 40\n" * 20,
    "experiment_cfg/initial_actions.npz": b"N" * 700,
    "model-00001-of-00002.safetensors": b"W" * 5000,
    "model-00002-of-00002.safetensors": b"V" * 3000,
    "model.safetensors.index.json": b"{}",
}
LFS_PATHS = {"experiment_cfg/initial_actions.npz", "model-00001-of-00002.safetensors", "model-00002-of-00002.safetensors"}
# On the hub, and not downloaded by design (hf.py puts them in the grey list).
NOT_DOWNLOADED = [plain_item("README.md", b"# robot\n"), plain_item(".gitattributes", b"*.npz filter=lfs\n"),
                  lfs_item("figure.png", b"PNG" * 50), lfs_item("training_args.bin", b"B" * 90)]
BIG, SMALL, WEIGHTS2 = "model-00001-of-00002.safetensors", "config.json", "model-00002-of-00002.safetensors"


def hub_tree(content=None, masked=False, extra=None):
    content = CONTENT if content is None else content
    items = [{"type": "directory", "path": "experiment_cfg", "size": 0, "oid": "d" * 40}]
    for path, data in content.items():
        items.append(lfs_item(path, data, MASK if masked else None) if path in LFS_PATHS else plain_item(path, data))
    return items + NOT_DOWNLOADED + list(extra or [])


def lay(models, repo, label, files):
    """Put `files` ({path in the repository: bytes}) where the page puts a checkpoint."""
    base = Path(models) / hc.CheckpointLayout.repo_folder(repo) / label
    for rel, data in files.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return base


class Hub:
    """Stands in for the network, and for where the models disk is: for the length of a `with`."""

    def __init__(self, models, trees, configs=None):
        self.models = Path(models)
        self.trees = trees
        self.configs = configs or {}

    def request(self, path, timeout=12, all_pages=False):
        repo = path.split("/tree/")[0][len("models/"):]
        return self.trees.get(repo, {"_error": "404"})

    def __enter__(self):
        self.saved = (hf._hf_request, hf._fetch_repo_config, hf.models_dir_from_config, hf.parse_config,
                      routes.models_dir_from_config, routes.parse_config, locator.current_locations)
        hf._hf_request = self.request
        hf._fetch_repo_config = lambda repo: self.configs.get(repo, {"dtype": "bfloat16"})
        hf.models_dir_from_config = routes.models_dir_from_config = lambda _cfg: self.models
        hf.parse_config = routes.parse_config = lambda *a, **kw: {}
        locator.current_locations = lambda wait=False: locator.Locations([])
        return self

    def __exit__(self, *exc):
        (hf._hf_request, hf._fetch_repo_config, hf.models_dir_from_config, hf.parse_config,
         routes.models_dir_from_config, routes.parse_config, locator.current_locations) = self.saved


class FakeHandler:
    def __init__(self):
        self.sent = []

    def send_json(self, doc, *a, **kw):
        self.sent.append(doc)


def wait(job_id, limit=10.0):
    deadline = time.time() + limit
    while time.time() < deadline:
        job = hv.verify_status(job_id)["job"]
        if job and job["done"]:
            return job
        time.sleep(0.01)
    return hv.verify_status(job_id)["job"]


def verify(hub, repo=REPO):
    """POST the route, then wait for the job: (the route's answer, the finished job or None)."""
    with hub:
        h = FakeHandler()
        routes._post_api_hf_verify(h, None, {"repo": repo})
        answer = h.sent[-1]
        return answer, (wait(answer["jobId"]) if answer.get("ok") else None)


def rows_of(job, index=0):
    return job["checkpoints"][index]["files"]


def summary(**counts):
    return {"files": 0, "pending": 0, **{state: 0 for state in hc.CheckpointFile.STATES}, **counts}


def main():
    print("the digests:")
    with tempfile.TemporaryDirectory() as tmp:
        hello, empty = Path(tmp) / "hello", Path(tmp) / "empty"
        hello.write_bytes(b"hello world\n")
        empty.write_bytes(b"")
        check(hv.file_digest(hello, "git-sha1") == HELLO_GIT_ID,
              "a git blob id is what `git hash-object` says: the sha1 of \"blob <size>\", a NUL and the bytes")
        check(hv.file_digest(empty, "git-sha1") == EMPTY_GIT_ID, "…and an empty file's is the well-known one")
        check(hv.file_digest(hello, "sha256") == HELLO_SHA256 == hv.file_sha256(hello), "sha256 is the sha256 of the bytes, by either name")
        check(hv.file_digest(hello, "git-sha1") != hashlib.sha1(b"hello world\n").hexdigest(),
              "negative: the sha1 of the bytes alone is not the git id")
        check(hv.file_digest(hello, "sha256") == HELLO_SHA256 and hv.file_digest(hello, "git-sha1") == HELLO_GIT_ID,
              "one file has two digests and the cache keeps them apart: asking for the other kind later does not answer with the first")
        try:
            hv.file_digest(hello, "hidden")
            check(False, "no digest to compute for a hidden hash — must refuse")
        except ValueError:
            check(True, "a kind with no digest is refused, not computed as something else")

    print("a folder with every file:")
    models = _TMP / "whole"
    lay(models, REPO, "BF16", CONTENT)
    # Extras on disk that the plan does not hold change nothing.
    lay(models, REPO, "BF16", {"README.md": b"# robot (edited)\n", "notes.txt": b"mine"})
    answer, job = verify(Hub(models, {REPO: hub_tree()}))
    check(answer.get("ok") is True and job and job["done"] and not job["error"], f"the job runs to its end (got {answer}, {job and job['error']})")
    check(json.loads(json.dumps(job)) == job, "the whole answer is plain data: it goes through JSON and comes back the same")
    check(job["files"] == {} and len(job["checkpoints"]) == 1, "no GGUF rows; one copy")
    copy = job["checkpoints"][0]
    check(copy["folder"] == "Robot-3B/acme/BF16", f"the copy is named by its folder (got {copy['folder']})")
    rows = copy["files"]
    check(sorted(rows) == sorted(CONTENT), f"a row for every file of the plan, by its path in the repository (got {sorted(rows)})")
    check(all(r["state"] == "same" for r in rows.values()), "every file is the same as on the hub")
    w = CONTENT[BIG]
    check(rows[BIG] == {"state": "same", "hash": "sha256", "expectedSize": 5000, "size": 5000, "sha256": sha(w), "expected": sha(w)},
          f"an LFS file: compared by sha256, both sides in the row (got {rows[BIG]})")
    c = CONTENT[SMALL]
    check(rows[SMALL] == {"state": "same", "hash": "git-sha1", "expectedSize": len(c), "size": len(c), "gitSha1": git_id(c), "expected": git_id(c)},
          f"an ordinary file: compared by its git blob id (got {rows[SMALL]})")
    check(rows["SUCCESS"] == {"state": "same", "hash": "git-sha1", "expectedSize": 0, "size": 0, "gitSha1": EMPTY_GIT_ID, "expected": EMPTY_GIT_ID},
          "an empty file is a file: same, by its git id")
    check(rows["experiment_cfg/conf.yaml"]["state"] == "same" and rows["experiment_cfg/initial_actions.npz"]["hash"] == "sha256",
          "a folder of the repository keeps its place: experiment_cfg/ is found, by its path")
    check(copy["summary"] == summary(files=7, same=7), f"the summary counts them (got {copy['summary']})")
    check("README.md" not in rows and "notes.txt" not in rows and ".gitattributes" not in rows,
          "negative: the README on disk, a note of the owner's and the hub's .gitattributes are no rows — the plan does not hold them")
    total = sum(len(d) for d in CONTENT.values())
    check((job["totalFiles"], job["totalBytes"], job["bytesDone"]) == (7, total, total), f"progress counts every byte read (got {job['totalFiles']}, {job['totalBytes']}, {job['bytesDone']})")

    print("not downloaded by design is not missing:")
    models = _TMP / "design"
    lay(models, REPO, "BF16", CONTENT)
    answer, job = verify(Hub(models, {REPO: hub_tree()}))
    check(job and job["checkpoints"][0]["summary"] == summary(files=7, same=7)
          and not {"README.md", ".gitattributes", "figure.png", "training_args.bin"} & set(rows_of(job)),
          "the README, .gitattributes, a picture and a .bin the plan leaves out are on the hub and not on disk: no row, no finding")

    print("a missing file is named:")
    models = _TMP / "missing"
    lay(models, REPO, "BF16", {p: d for p, d in CONTENT.items() if p not in (WEIGHTS2, "experiment_cfg/conf.yaml")})
    answer, job = verify(Hub(models, {REPO: hub_tree()}))
    rows = rows_of(job)
    check(rows[WEIGHTS2] == {"state": "missing", "hash": "sha256", "expectedSize": 3000},
          f"the weights that are not there: missing, with the size the hub says (got {rows[WEIGHTS2]})")
    check(rows["experiment_cfg/conf.yaml"]["state"] == "missing", "a file of a folder of the repository that is not there is missing too")
    check(job["checkpoints"][0]["summary"] == summary(files=7, same=5, missing=2), f"the summary says 2 missing, 5 same (got {job['checkpoints'][0]['summary']})")
    check(rows[BIG]["state"] == "same" and rows[SMALL]["state"] == "same", "negative: the files that are there are still checked")
    check(job["totalFiles"] == 5 and job["totalBytes"] == total - 3000 - len(CONTENT["experiment_cfg/conf.yaml"]),
          "negative: nothing is read for a file that is not there")

    print("a file of the wrong size is named, and is not read:")
    models = _TMP / "wrong-size"
    lay(models, REPO, "BF16", dict(CONTENT, **{BIG: b"W" * 4999, SMALL: CONTENT[SMALL] + b" "}))
    answer, job = verify(Hub(models, {REPO: hub_tree()}))
    rows = rows_of(job)
    check(rows[BIG] == {"state": "wrong-size", "hash": "sha256", "expectedSize": 5000, "size": 4999},
          f"a truncated weights file: wrong-size, both sizes in the row, and no digest (got {rows[BIG]})")
    check(rows[SMALL]["state"] == "wrong-size" and rows[SMALL]["size"] == len(CONTENT[SMALL]) + 1, "an ordinary file of another size is wrong-size too")
    check(job["checkpoints"][0]["summary"] == summary(files=7, same=5, **{"wrong-size": 2}), f"the summary counts them apart from missing (got {job['checkpoints'][0]['summary']})")
    check(job["totalBytes"] == total - 5000 - len(CONTENT[SMALL]) and job["bytesDone"] == job["totalBytes"],
          "a file of another size cannot be the same one, so its bytes are not read (the 5 GB file costs nothing)")

    print("another build under the same name differs:")
    models = _TMP / "differs"
    same_size_other_bytes = {BIG: b"X" * 5000, SMALL: b'{"model_type": "other"}\n'}
    assert len(same_size_other_bytes[SMALL]) == len(CONTENT[SMALL])
    lay(models, REPO, "BF16", dict(CONTENT, **same_size_other_bytes))
    answer, job = verify(Hub(models, {REPO: hub_tree()}))
    rows = rows_of(job)
    check(rows[BIG] == {"state": "differs", "hash": "sha256", "expectedSize": 5000, "size": 5000, "sha256": sha(b"X" * 5000), "expected": sha(CONTENT[BIG])},
          f"same size, other bytes: differs — what was found and what the hub has, side by side (got {rows[BIG]})")
    check(rows[SMALL]["state"] == "differs" and rows[SMALL]["gitSha1"] == git_id(same_size_other_bytes[SMALL]) and rows[SMALL]["expected"] == git_id(CONTENT[SMALL]),
          "an ordinary file with other bytes differs by its git id")
    check(job["checkpoints"][0]["summary"] == summary(files=7, same=5, differs=2), "negative: the other five stay same")

    print("a gated repository: the hash is hidden, and the answer says so:")
    models = _TMP / "gated"
    gated_repo = "nvidia/Gated-Policy-2B"
    lay(models, gated_repo, "BF16", CONTENT)       # the copy sits under BF16 …
    hub = Hub(models, {gated_repo: hub_tree(masked=True)}, configs={gated_repo: {"ok": False, "error": "HTTP Error 401: Unauthorized"}})
    with hub:                                      # … and today's listing, whose config.json cannot be read, says SAFETENSORS
        today = hf.hf_list_files(gated_repo)["safetensors"]
    check(today["format"] == "SAFETENSORS" and all(f["hashHidden"] for f in today["files"] if f["path"] in LFS_PATHS),
          "the setting: a listing that labels the folder SAFETENSORS and hides the LFS hashes")
    answer, job = verify(hub, gated_repo)
    check(answer.get("ok") is True and job and not job["error"], f"a gated repository is not a failure (got {answer})")
    rows = rows_of(job)
    check(job["checkpoints"][0]["folder"] == "Gated-Policy-2B/nvidia/BF16",
          f"the copy is found where it lies, not where today's label would put it (got {job['checkpoints'][0]['folder']})")
    check(rows[BIG] == {"state": "size-only", "hash": "hidden", "expectedSize": 5000, "size": 5000},
          f"hidden hash: size-only, the hash is said to be hidden, and nothing was computed (got {rows[BIG]})")
    check(rows[BIG]["state"] not in ("same", "differs"), "negative: neither a pass nor a failure")
    check({p for p, r in rows.items() if r["state"] == "size-only"} == LFS_PATHS, "every LFS file is size-only, and only those")
    check(rows[SMALL]["state"] == "same" and rows[SMALL]["hash"] == "git-sha1",
          "negative: the ordinary files of a gated repository are still verified by their git ids")
    check(job["checkpoints"][0]["summary"] == summary(files=7, same=4, **{"size-only": 3}), f"the summary counts the unverified apart (got {job['checkpoints'][0]['summary']})")
    small_total = sum(len(d) for p, d in CONTENT.items() if p not in LFS_PATHS)
    check((job["totalFiles"], job["totalBytes"], job["bytesDone"]) == (4, small_total, small_total),
          f"only the ordinary files are read: the weights cost nothing to a check that has no hash to hold them against (got {job['totalBytes']})")

    print("hidden hashes still catch a wrong size:")
    models = _TMP / "gated-size"
    lay(models, gated_repo, "BF16", dict(CONTENT, **{BIG: b"W" * 4000}))
    answer, job = verify(Hub(models, {gated_repo: hub_tree(masked=True)}), gated_repo)
    check(rows_of(job)[BIG]["state"] == "wrong-size", "the size is compared without the hash: a truncated file is named even when the hub hides its hash")
    models = _TMP / "gated-other-bytes"
    lay(models, gated_repo, "BF16", dict(CONTENT, **{BIG: b"X" * 5000}))
    answer, job = verify(Hub(models, {gated_repo: hub_tree(masked=True)}), gated_repo)
    check(rows_of(job)[BIG]["state"] == "size-only" and "sha256" not in rows_of(job)[BIG],
          "the limit, said out loud: other bytes of the same size cannot be told apart without a hash — the row stays size-only, which is NOT verified")

    print("a copy that needs no reading still answers:")
    models = _TMP / "no-reading"
    lay(models, gated_repo, "BF16", {BIG: CONTENT[BIG]})
    answer, job = verify(Hub(models, {gated_repo: hub_tree(masked=True)}), gated_repo)
    check(answer.get("ok") is True and job and job["done"] and not job["error"]
          and job["checkpoints"][0]["summary"] == summary(files=7, missing=6, **{"size-only": 1}) and job["totalFiles"] == 0,
          f"one hidden-hash file and six missing: every row is settled without a byte read, and the job still answers (got {answer})")

    print("a copy under another label, two copies, a GGUF folder beside them:")
    models = _TMP / "labels"
    lay(models, REPO, "BF16", CONTENT)
    lay(models, REPO, "SAFETENSORS", {SMALL: CONTENT[SMALL]})
    lay(models, REPO, "Q4_K_M", {"Robot-3B-Q4_K_M.gguf": b"G" * 40})
    lay(models, REPO, ".hidden", CONTENT)
    answer, job = verify(Hub(models, {REPO: hub_tree()}))
    check([c["folder"] for c in job["checkpoints"]] == ["Robot-3B/acme/BF16", "Robot-3B/acme/SAFETENSORS"],
          f"every folder that holds a file of the plan is a copy, in order; a GGUF quant folder and a hidden one are not (got {[c['folder'] for c in job['checkpoints']]})")
    check(job["checkpoints"][0]["summary"] == summary(files=7, same=7)
          and job["checkpoints"][1]["summary"] == summary(files=7, same=1, missing=6),
          "each copy answers on its own: the whole one is same, the one with a single file names the other six")
    check(job["files"] == {}, "negative: the GGUF file lying beside is not a row of the checkpoint (the repository has no GGUF listing)")

    print("a link is the file it leads to; a path never leads out of the folder:")
    models = _TMP / "links"
    base = lay(models, REPO, "BF16", {p: d for p, d in CONTENT.items() if p not in (SMALL, "model.safetensors.index.json", "SUCCESS")})
    (base / "SUCCESS").mkdir()
    (Path(models) / "shared").mkdir()
    (Path(models) / "shared" / "config.json").write_bytes(CONTENT[SMALL])
    os.symlink("../../../shared/config.json", base / SMALL)
    os.symlink("../../../shared/nowhere.json", base / "model.safetensors.index.json")
    outside = Path(models) / "Robot-3B" / "up.json"
    outside.write_bytes(b"{}")
    escape = plain_item("../../up.json", b"{}")
    answer, job = verify(Hub(models, {REPO: hub_tree(extra=[escape])}))
    rows = rows_of(job)
    check(rows[SMALL]["state"] == "same", "a link to a file with the right bytes is that file")
    check(rows["model.safetensors.index.json"]["state"] == "missing", "a link to nothing is a file that is not there")
    check(rows["SUCCESS"]["state"] == "missing", "a folder where the file should be is not the file")
    check(rows["../../up.json"]["state"] == "missing",
          "negative: a path of \"..\" steps is looked up INSIDE the copy; the file it names outside is not found")

    print("a file that cannot even be looked at is not a file that is not there:")
    models = _TMP / "no-access"
    lay(models, REPO, "BF16", CONTENT)
    real_stat = Path.stat

    def stat_denied(self, *a, **kw):
        if self.name == SMALL:
            raise PermissionError(13, "Permission denied", str(self))
        return real_stat(self, *a, **kw)

    with Hub(models, {REPO: hub_tree()}):
        listing = hf.hf_list_files(REPO)
        Path.stat = stat_denied
        try:
            copies = hc.CheckpointFinder(models).copies(REPO, listing["safetensors"])
        finally:
            Path.stat = real_stat
    job = wait(hv.start_verify(REPO, [], {}, copies))
    row = rows_of(job)[SMALL]
    check(row["state"] == "unreadable" and "Permission denied" in row["error"] and "size" not in row,
          f"a file whose look is refused is unreadable, with the reason, and no size is made up for it (got {row})")
    check(job["checkpoints"][0]["summary"] == summary(files=7, same=6, unreadable=1),
          "negative: it is not called missing, and the six others are still checked")

    print("a file that vanishes between the look and the read:")
    models = _TMP / "vanish"
    lay(models, REPO, "BF16", CONTENT)
    with Hub(models, {REPO: hub_tree()}):
        listing = hf.hf_list_files(REPO)
        copies = hc.CheckpointFinder(models).copies(REPO, listing["safetensors"])
    (Path(models) / "Robot-3B" / "acme" / "BF16" / WEIGHTS2).unlink()
    job = wait(hv.start_verify(REPO, [], {}, copies))
    row = rows_of(job)[WEIGHTS2]
    check(row["state"] == "unreadable" and row["error"] and row["size"] == 3000,
          f"unreadable, with the reason — not differs, not missing (got {row})")
    check(job["done"] and not job["error"] and job["checkpoints"][0]["summary"] == summary(files=7, same=6, unreadable=1),
          "one unreadable row does not stop the job: the six others are checked")

    print("a half-read copy does not read as a whole one:")
    models = _TMP / "flight"
    lay(models, REPO, "BF16", {p: d for p, d in CONTENT.items() if p != WEIGHTS2})
    gate, entered, real = threading.Event(), threading.Event(), hv.file_digest

    def slow(path, kind, on_progress=None):
        entered.set()
        gate.wait(10)
        return real(path, kind, on_progress)

    hv.file_digest = slow
    try:
        with Hub(models, {REPO: hub_tree()}):
            h = FakeHandler()
            routes._post_api_hf_verify(h, None, {"repo": REPO})
            jid = h.sent[-1]["jobId"]
            entered.wait(10)
            mid = hv.verify_status(jid)["job"]
        check(mid["done"] is False and mid["checkpoints"][0]["summary"] == summary(files=7, pending=6, missing=1),
              f"while the job reads: the missing file is already in, six are still pending (got {mid['checkpoints'][0]['summary']})")
        check(mid["checkpoints"][0]["files"].keys() == {WEIGHTS2}, "only the rows that are settled are in the answer so far")
        route = FakeHandler()
        routes._get_api_hf_verify(route, urllib.parse.urlparse(f"/api/hf/verify?job={jid}"))
        check(route.sent[-1]["job"]["checkpoints"][0]["summary"]["pending"] == 6, "the GET route carries the section as the job has it")
    finally:
        gate.set()
        hv.file_digest = real
    job = wait(jid)
    check(job["done"] and job["checkpoints"][0]["summary"] == summary(files=7, same=6, missing=1), "released, the job ends with nothing pending")
    check(hv.verify_status("no-such-job")["job"] is None, "an unknown job is None, as before")

    print("a repository with both kinds of file:")
    models = _TMP / "both"
    both = "acme/Both-7B"
    gguf = b"G" * 400
    mm = b"M" * 60
    cfg, weights = b'{"a": 1}\n', b"S" * 900
    lay(models, both, "Q4_K_M", {"Both-7B-Q4_K_M.gguf": gguf, "mmproj-Both-7B-f16.gguf": mm})
    lay(models, both, "BF16", {"config.json": cfg, "model.safetensors": weights})
    tree = [lfs_item("Both-7B-Q4_K_M.gguf", gguf), lfs_item("mmproj-Both-7B-f16.gguf", mm, MASK),
            plain_item("config.json", cfg), lfs_item("model.safetensors", weights)]
    answer, job = verify(Hub(models, {both: tree}), both)
    check(job and sorted(job["files"]) == ["Both-7B-Q4_K_M.gguf", "mmproj-Both-7B-f16.gguf"]
          and [c["folder"] for c in job["checkpoints"]] == ["Both-7B/acme/BF16"],
          f"the GGUF files answer in `files` by name, the checkpoint in `checkpoints` by folder (got {sorted(job['files'])}, {[c['folder'] for c in job['checkpoints']]})")
    check(job["files"]["Both-7B-Q4_K_M.gguf"] == {"state": "same", "sha256": sha(gguf), "expected": sha(gguf), "hash": "sha256"},
          f"a GGUF row keeps its shape and says which hash it was held against (got {job['files']['Both-7B-Q4_K_M.gguf']})")
    check(job["files"]["mmproj-Both-7B-f16.gguf"] == {"state": "unknown", "sha256": sha(mm), "expected": "", "hash": "hidden"},
          f"negative: a GGUF file whose hash is hidden is unknown — it used to be a different file, from the mask (got {job['files']['mmproj-Both-7B-f16.gguf']})")
    check(rows_of(job)["config.json"]["state"] == "same" and rows_of(job)["model.safetensors"]["state"] == "same",
          "the checkpoint is verified beside them")
    check((job["totalFiles"], job["totalBytes"]) == (4, len(gguf) + len(mm) + len(cfg) + len(weights)),
          "one job, one progress: the bytes of both kinds are counted together")

    print("a GGUF copy of a repository that also has a checkpoint is not 'files missing':")
    models = _TMP / "gguf-only"
    lay(models, both, "Q4_K_M", {"Both-7B-Q4_K_M.gguf": gguf})
    answer, job = verify(Hub(models, {both: tree}), both)
    check(job and sorted(job["files"]) == ["Both-7B-Q4_K_M.gguf"] and job["checkpoints"] == [],
          "the checkpoint was never downloaded: no copy, no rows — and the GGUF file is verified as before")
    check(job["files"]["Both-7B-Q4_K_M.gguf"]["state"] == "same", "the GGUF answer is whole")

    print("nothing on disk is a refusal:")
    def empty_folder(models):
        (models / "Robot-3B" / "acme" / "BF16").mkdir(parents=True)

    for n, (label, populate) in enumerate((
            ("no folder at all", lambda m: None),
            ("a folder of the model with nothing in it", empty_folder),
            ("files that the plan does not hold", lambda m: lay(m, REPO, "BF16", {"notes.txt": b"x", "README.md": b"y"})))):
        models = _TMP / f"nothing-{n}"
        models.mkdir()
        populate(models)
        answer, job = verify(Hub(models, {REPO: hub_tree()}))
        check(answer.get("ok") is False and "on disk" in str(answer.get("error")) and job is None,
              f"{label}: `ok: false`, \"on disk\" in the reason, no job (got {answer})")
    answer, job = verify(Hub(_TMP / "whole", {REPO: {"_error": "HTTP Error 404"}}))
    check(answer.get("ok") is False and "404" in answer.get("error", ""), "Hugging Face unreachable is the refusal it was, with its reason")
    h = FakeHandler()
    with Hub(_TMP / "whole", {}):
        routes._post_api_hf_verify(h, None, {"repo": "no-slash"})
    check(h.sent[-1].get("ok") is False, "an invalid repo id is the refusal it was")

    print("a folder that cannot be read is a refusal, not 'nothing on disk':")
    real_os = hc.os

    def denied(path):
        raise PermissionError(13, "Permission denied", str(path))

    # Only the finder's view of `os` is replaced: the GGUF scan beside it walks folders too.
    hc.os = types.SimpleNamespace(scandir=denied)
    try:
        answer, job = verify(Hub(_TMP / "whole", {REPO: hub_tree()}))
    finally:
        hc.os = real_os
    check(answer.get("ok") is False and "cannot read Robot-3B/acme" in answer.get("error", "") and "on disk" not in answer.get("error", ""),
          f"the reason names the folder and is not the claim that nothing is there (got {answer})")
    check(hc.CheckpointFinder(_TMP / "whole").copies(REPO, None) == [] and hc.CheckpointFinder(_TMP / "whole").copies(REPO, {"files": []}) == [],
          "a repository with no plan has no copy to find")
    check(hc.CheckpointFinder(_TMP / "no-such-models-dir").copies(REPO, {"files": [{"path": "a", "name": "a", "size": 1}]}) == [],
          "negative: a models directory that is not there holds no copy — and no exception")
    (_TMP / "model-is-a-file").mkdir()
    (_TMP / "model-is-a-file" / "Robot-3B").write_bytes(b"not a folder")
    check(hc.CheckpointFinder(_TMP / "model-is-a-file").copies(REPO, {"files": [{"path": "a", "name": "a", "size": 1}]}) == [],
          "negative: a file where the model's folder should be holds no copy either")

    print("the vocabulary of a row, by value:")
    f = hc.CheckpointFile("w.safetensors", 10, HubHash("sha256", "a" * 64), {"path": "/x", "size": 10, "mtime": 1})
    check(f.judged("a" * 64)["state"] == "same" and f.judged("b" * 64)["state"] == "differs", "the digest decides same or differs, and nothing else does")
    check(f.settled() is None, "a file of the right size with a hash to hold it against is the one case that needs reading")
    check(hc.CheckpointFile("m", 10, HubHash("hidden"), {"path": "/x", "size": 10}).settled()["state"] == "size-only"
          and hc.CheckpointFile("m", 10, HubHash("none"), {"path": "/x", "size": 10}).settled()["hash"] == "none",
          "no hash from the hub is size-only whatever the reason, and the row names the reason")
    check(hc.CheckpointFile("m", 10, HubHash("hidden"), {"path": "/x", "error": "denied"}).settled()["state"] == "unreadable",
          "a file that cannot even be looked at is unreadable, before any question of hashes")
    check(hc.CheckpointResult(hc.CheckpointCopy("a/b/c", [])).summary() == summary(),
          "a copy with nothing in its plan summarises as nothing, not as a pass")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("hf verify checkpoint snapshots hold")


if __name__ == "__main__":
    main()
