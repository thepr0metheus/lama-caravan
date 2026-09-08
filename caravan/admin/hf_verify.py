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
correct: recomputing is cheaper than trusting a record that outlived a file
being replaced.
"""
import hashlib
import threading
import time
from pathlib import Path

from caravan.common.errors import AppError

#: (path, size, mtime in nanoseconds) → sha256. A file that got overwritten
#: must recompute, not answer with the old hash. Time is taken in
#: nanoseconds, not seconds: an overwrite at the same size within one second
#: is indistinguishable from "untouched" at second precision — the pin for
#: this stayed red while the key was seconds-based.
_hash_cache: dict = {}
_jobs: dict = {}
_lock = threading.Lock()

#: Read in large chunks: at 17 GB, the difference between 64 KiB and 4 MiB is
#: minutes.
CHUNK = 4 * 1024 * 1024
#: How many finished jobs are remembered. No more is needed: the page asks
#: for its own right after starting it.
KEEP_JOBS = 8


def file_sha256(path, on_progress=None):
    """A file's sha256, cached by (path, size, mtime)."""
    p = Path(path)
    st = p.stat()
    key = (str(p), st.st_size, int(getattr(st, "st_mtime_ns", 0) or int(st.st_mtime) * 10**9))
    with _lock:
        cached = _hash_cache.get(key)
    if cached:
        if on_progress:
            on_progress(st.st_size)
        return cached
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


def _run(job_id, pairs):
    job = _jobs[job_id]
    try:
        for index, (name, path, expected) in enumerate(pairs):
            with _lock:
                job["currentFile"] = name
                job["currentIdx"] = index
            def bump(n, _job=job):
                with _lock:
                    _job["bytesDone"] += n
            try:
                actual = file_sha256(path, on_progress=bump)
            except OSError as exc:
                with _lock:
                    job["files"][name] = {"state": "unreadable", "error": str(exc)}
                continue
            # No expected hash is not "matched". LFS doesn't store an oid for
            # every file (small ones sit as plain blobs), and silence here
            # would look like confirmation.
            state = "unknown" if not expected else ("same" if actual == expected else "differs")
            with _lock:
                job["files"][name] = {"state": state, "sha256": actual, "expected": expected}
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


def start_verify(repo, files, local_files):
    """Start verifying a repository. Returns the job id.

    `files` is what HF reported (name, size, oid); `local_files` is what
    hf_local_check found (name → {size, mtime, path}). Only files we actually
    have are checked: there's nothing to hash for one that isn't there.
    """
    repo = str(repo or "").strip()
    if not repo:
        raise AppError("missing repo", 400)
    pairs = []
    total = 0
    for f in files or []:
        name = str(f.get("name") or "")
        local = (local_files or {}).get(name) or {}
        path = local.get("path")
        if not name or not path:
            continue
        pairs.append((name, path, str(f.get("oid") or "")))
        total += int(local.get("size") or 0)
    if not pairs:
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
                         "files": {}, "totalFiles": len(pairs), "totalBytes": total,
                         "bytesDone": 0, "currentFile": "", "currentIdx": 0,
                         "startedAt": time.time(), "finishedAt": None}
    threading.Thread(target=_run, args=(job_id, pairs), daemon=True).start()
    return job_id


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
        return {"ok": True, "job": dict(job, files=dict(job["files"]))}
