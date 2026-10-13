"""Comparing the local copy to Hugging Face by content, not by guesswork.

Size and date answer fast and are almost always right — but "almost" is
expensive here: `google_gemma-4-31B-it-Q4_K_M.gguf` once differed by 1,760
bytes out of 19.6 GB, and size alone can't say whether that's re-uploaded
metadata or rebuilt weights. LFS stores every file's sha256, and that gives
the definitive answer.

Hashing a 17 GB file is minutes and a full pass over the disk, so:

* on button press only, never on its own;
* the result is cached by (path, size, mtime) — a touched file is checked
  again, an untouched one answers instantly;
* the work runs in a thread with progress, so the page doesn't go silent.

The cache lives in process memory. A controller restart loses it, and that's
the right way round: recomputing is cheaper than trusting a record that
outlived a file being replaced.

A repository can be a folder too: a safetensors checkpoint, dozens of files
under <model>/<author>/<FORMAT>/ (hf_checkpoint.py). Its files answer in their
own section of the job, `checkpoints`, one entry per folder holding a copy,
because they are not the same kind of answer: the checkpoint is expected WHOLE,
so a file that is not there is named, a file of the wrong size is named
without being read, and a file whose hash the hub does not give is checked by
size only and SAYS so (`size-only`) — a gated repository hides its LFS hashes,
and that is neither a pass nor a failure. An ordinary git file has no sha256,
only the git blob id, and is checked by that.

The entry points stay functions (`start_verify`, `verify_status`, `file_digest`):
routes.py calls them as such, and the jobs and the digest cache they share are
one table per process. What differs by kind of file is an object each, not a
branch on the kind: `_GgufWork` builds a GGUF file's row, `_CheckpointWork` a
checkpoint file's (the rules for which are in hf_checkpoint.py).
"""
import hashlib
import threading
import time
from pathlib import Path

from caravan.admin.hf_checkpoint import CheckpointResult
from caravan.admin.hub_hash import HubHash
from caravan.common.errors import AppError

#: (kind, path, size, mtime in nanoseconds) → digest. A file that got
#: overwritten must recompute, not answer with the old hash. Time is taken in
#: nanoseconds, not seconds: an overwrite at the same size within one second
#: is indistinguishable from "untouched" at second precision — the pin for
#: this stayed red while the key was seconds-based. The kind is in the key
#: because one file has two digests (its sha256 and its git blob id).
_hash_cache: dict = {}
_jobs: dict = {}
_lock = threading.Lock()

#: Read in large chunks: at 17 GB, the difference between 64 KiB and 4 MiB is
#: minutes.
CHUNK = 4 * 1024 * 1024
#: How many finished jobs are remembered. No more is needed: the page asks
#: for its own right after starting it.
KEEP_JOBS = 8


def file_digest(path, kind, on_progress=None):
    """A file's digest of the kind the hub gave for it, cached by (kind, path, size,
    mtime): HubHash.SHA256 is the sha256 of the bytes, HubHash.GIT_SHA1 the git
    blob id."""
    if kind not in (HubHash.SHA256, HubHash.GIT_SHA1):
        raise ValueError(f"no digest to compute for a {kind!r} hash")
    p = Path(path)
    st = p.stat()
    key = (kind, str(p), st.st_size, int(getattr(st, "st_mtime_ns", 0) or int(st.st_mtime) * 10**9))
    with _lock:
        cached = _hash_cache.get(key)
    if cached:
        if on_progress:
            on_progress(st.st_size)
        return cached
    if kind == HubHash.GIT_SHA1:
        # Git names a file's content by hashing "blob <size>" and a NUL first,
        # then the bytes: the same bytes alone are another sha1.
        digest = hashlib.sha1(b"blob %d\0" % st.st_size, usedforsecurity=False)
    else:
        digest = hashlib.sha256()
    with open(p, "rb") as fh:
        while True:
            chunk = fh.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            if on_progress:
                on_progress(len(chunk))
    value = digest.hexdigest()
    with _lock:
        _hash_cache[key] = value
    return value


def file_sha256(path, on_progress=None):
    """A file's sha256, cached by (path, size, mtime)."""
    return file_digest(path, HubHash.SHA256, on_progress)


class _GgufWork:
    """A GGUF file on disk: its sha256 against the one the hub gave."""

    #: What is computed. A GGUF file is always an LFS file, so always a sha256.
    kind = HubHash.SHA256

    def __init__(self, name, path, hub_hash):
        self.label = name
        self.path = path
        self.hub_hash = hub_hash

    def judged(self, actual):
        # No expected hash is not "matched". LFS doesn't store an oid for
        # every file (small ones sit as plain blobs), a gated repository masks
        # it, and silence here would look like confirmation.
        expected = self.hub_hash.value if self.hub_hash.kind == HubHash.SHA256 else ""
        state = "unknown" if not expected else ("same" if actual == expected else "differs")
        return {"state": state, "sha256": actual, "expected": expected, "hash": self.hub_hash.kind}

    def unreadable(self, exc):
        return {"state": "unreadable", "error": str(exc), "hash": self.hub_hash.kind}

    def store(self, job, row):
        job["files"][self.label] = row


class _CheckpointWork:
    """A file of a checkpoint whose size is right and whose hash the hub gave —
    the one case of a checkpoint that has bytes to read."""

    def __init__(self, result, file):
        self.result = result
        self.file = file
        self.label = file.repo_path
        self.path = file.local["path"]
        self.kind = file.hub_hash.kind

    def judged(self, actual):
        return self.file.judged(actual)

    def unreadable(self, exc):
        return self.file.unreadable(exc)

    def store(self, job, row):
        self.result.rows[self.file.repo_path] = row


def _run(job_id, works):
    job = _jobs[job_id]
    try:
        for index, work in enumerate(works):
            with _lock:
                job["currentFile"] = work.label
                job["currentIdx"] = index
            def bump(n, _job=job):
                with _lock:
                    _job["bytesDone"] += n
            try:
                actual = file_digest(work.path, work.kind, on_progress=bump)
            except OSError as exc:
                row = work.unreadable(exc)
            else:
                row = work.judged(actual)
            with _lock:
                work.store(job, row)
    except Exception as exc:  # noqa: BLE001
        with _lock:
            job["error"] = str(exc)
    finally:
        with _lock:
            job["done"] = True
            job["finishedAt"] = time.time()
        _trim_jobs()


def _trim_jobs():
    with _lock:
        done = [(j.get("finishedAt") or 0, jid) for jid, j in _jobs.items() if j.get("done")]
        for _t, jid in sorted(done)[:-KEEP_JOBS]:
            _jobs.pop(jid, None)


def start_verify(repo, files, local_files, copies=None):
    """Start verifying a repository. Returns the job id.

    `files` is what HF reported (name, size, oid…); `local_files` is what
    hf_local_check found (name → {size, mtime, path}). Only GGUF files we
    actually have are checked: there's nothing to hash for one that isn't there.

    `copies` are the checkpoint folders hf_checkpoint found on the disk, for a
    repository that is a folder. There a file that is not there IS an answer, so
    every row that needs no reading (missing, wrong size, hash not given) is
    settled right here, and only the files with a hash to compare become work.
    """
    repo = str(repo or "").strip()
    if not repo:
        raise AppError("missing repo", 400)
    works = []
    total = 0
    for f in files or []:
        name = str(f.get("name") or "")
        local = (local_files or {}).get(name) or {}
        path = local.get("path")
        if not name or not path:
            continue
        works.append(_GgufWork(name, path, HubHash.from_entry(f)))
        total += int(local.get("size") or 0)
    results = []
    for copy in copies or []:
        result = CheckpointResult(copy)
        results.append(result)
        for file in copy.files:
            row = file.settled()
            if row is not None:
                result.rows[file.repo_path] = row
            else:
                works.append(_CheckpointWork(result, file))
                total += file.local["size"]
    if not works and not results:
        raise AppError("nothing of this repo is on disk", 400)
    # One job per repository: two parallel passes over the same files would
    # be twice the reading for the same answer.
    with _lock:
        for jid, job in _jobs.items():
            if not job.get("done") and job.get("repo") == repo:
                return jid
    job_id = f"{int(time.time())}-{len(_jobs)}"
    with _lock:
        _jobs[job_id] = {"id": job_id, "repo": repo, "done": False, "error": None,
                         "files": {}, "checkpoints": results,
                         "totalFiles": len(works), "totalBytes": total,
                         "bytesDone": 0, "currentFile": "", "currentIdx": 0,
                         "startedAt": time.time(), "finishedAt": None}
    threading.Thread(target=_run, args=(job_id, works), daemon=True).start()
    return job_id


def _snapshot(job):
    """The job as an answer: copies the caller may keep, not the live records the thread writes to."""
    return dict(job, files=dict(job["files"]), checkpoints=[r.snapshot() for r in job["checkpoints"]])


def verify_status(job_id="", repo=""):
    """A job's status — by id, or by repository (the latter for the page)."""
    with _lock:
        if job_id:
            job = _jobs.get(str(job_id))
        else:
            same = [j for j in _jobs.values() if j.get("repo") == str(repo or "")]
            job = sorted(same, key=lambda j: j.get("startedAt") or 0)[-1] if same else None
        if not job:
            return {"ok": True, "job": None}
        return {"ok": True, "job": _snapshot(job)}
