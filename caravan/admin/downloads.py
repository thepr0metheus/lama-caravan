"""Background HuggingFace GGUF downloads with per-job progress tracking.

Jobs live in memory only, so a restart — a deploy, most often — loses every
in-flight one. The bytes survive (see the ".part" comment in _run_download_job),
but the JOB does not, and an empty job list reads exactly like "everything
finished". A 39 GB download was cut off at 15 GB that way on 2026-08-14 and the
panel showed nothing at all.

So each ".part" carries a small ".part.json" manifest naming the repo and the
file it came from. That is the whole reason the manifest exists: on startup the
partials on disk can be listed as INTERRUPTED instead of vanishing, and resumed
without asking the operator to remember what they were downloading.
"""
import json
import os
import secrets as secrets_mod
import threading
import time
import urllib.request
from pathlib import Path


_download_jobs: dict = {}

_download_jobs_lock = threading.Lock()

# Scanning the models tree costs a full walk, and the jobs endpoint is polled
# every couple of seconds while a download runs. Cache the result briefly.
_PART_SCAN_TTL = 5.0
_part_scan_cache: dict = {"at": 0.0, "dir": "", "rows": []}


def _manifest_path(tmp_path: Path) -> Path:
    return tmp_path.with_name(tmp_path.name + ".json")


def _write_manifest(tmp_path: Path, repo: str, f: dict) -> None:
    """Record what this partial is, so a restart can name and resume it."""
    try:
        _manifest_path(tmp_path).write_text(json.dumps({
            "repo": repo,
            "path": f.get("path") or "",
            "name": f.get("name") or "",
            "destDir": f.get("destDir") or "",
            "size": int(f.get("size") or 0),
            "started_at": time.time(),
        }), encoding="utf-8")
    except OSError:
        pass  # a missing manifest degrades to "interrupted, not resumable"


def _read_manifest(tmp_path: Path) -> dict:
    try:
        return json.loads(_manifest_path(tmp_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _drop_stale_partial(tmp_path: Path, repo: str, f: dict) -> None:
    """Discard a partial download left over from another file or another build.

    The repository, the path inside it, and the expected size must all match.
    No manifest also means discard: whose leftover it is becomes unknown, and
    "probably the same one" costs a whole model here.
    """
    if not tmp_path.exists():
        return
    saved = _read_manifest(tmp_path)
    same = (saved.get("repo") == repo
            and saved.get("path") == (f.get("path") or "")
            and int(saved.get("size") or 0) == int(f.get("size") or 0)
            and int(saved.get("size") or 0) > 0)
    if same:
        return
    try:
        tmp_path.unlink()
    except OSError:
        pass
    _drop_manifest(tmp_path)


def _drop_manifest(tmp_path: Path) -> None:
    try:
        _manifest_path(tmp_path).unlink()
    except OSError:
        pass


def _run_download_job(job_id: str, repo: str, files: list, models_dir: str, token: str):
    job = _download_jobs[job_id]
    try:
        for i, f in enumerate(files):
            with _download_jobs_lock:
                job["current_idx"] = i
                job["current_file"] = f["name"]
                job["current_path"] = _dest_path(f)
                job["file_bytes_done"] = 0
                job["file_bytes_total"] = f.get("size", 0)

            dest_dir = Path(models_dir) / f["destDir"]
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / f["name"]

            url = f"https://huggingface.co/{repo}/resolve/main/{f['path']}"
            headers = {"User-Agent": "lama-caravan/1.0"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            # Stream into "<name>.part" and os.replace() at the end: a
            # half-written file must never sit under the final .gguf name
            # (the model catalog would list it and a cell could try to load
            # it). The STABLE temp name is what makes downloads survive an
            # admin restart: a re-issued job finds the .part and resumes it
            # with an HTTP Range request instead of starting from zero.
            tmp_path = dest_dir / f"{f['name']}.part"
            # Rescue a partial from the older job-suffixed naming scheme.
            if not tmp_path.exists():
                legacy = sorted(dest_dir.glob(f"{f['name']}.part-*"))
                if legacy:
                    os.replace(legacy[-1], tmp_path)
                    for stray in legacy[:-1]:
                        try:
                            stray.unlink()
                        except OSError:
                            pass
            # A partial download from a DIFFERENT build is not a resume point.
            # A range request would glue a new tail onto an old head, and the
            # completeness check below compares only the byte COUNT and would
            # let such a splice through. The file then lands on top of the
            # working one, so the cost of getting this wrong is seventeen
            # silently corrupted gigabytes. Checked against the manifest
            # BEFORE overwriting it.
            _drop_stale_partial(tmp_path, repo, f)
            _write_manifest(tmp_path, repo, f)
            # Retry the transfer itself. HF's CDN drops long connections — twice
            # in one afternoon on a 23 GB and a 42 GB file — and until now a drop
            # ended the job: status "error", the .part kept, and nothing moving
            # until a person noticed and pressed Resume. The resume machinery was
            # already here; it simply had no caller but a human. Each attempt
            # re-reads the .part size, so a retry continues from where the last
            # byte landed rather than starting over.
            with _download_jobs_lock:
                done_before = job["total_bytes_done"]      # what earlier files added
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                offset = tmp_path.stat().st_size if tmp_path.exists() else 0
                headers.pop("Range", None)
                if offset:
                    headers["Range"] = f"bytes={offset}-"
                req = urllib.request.Request(url, headers=headers)
                with _download_jobs_lock:
                    job["attempt"] = attempt
                try:
                    with urllib.request.urlopen(req, timeout=120) as resp:
                        length = int(resp.headers.get("Content-Length") or 0)
                        if offset and resp.status == 206:
                            total = offset + length
                            mode = "ab"
                        else:
                            # Server ignored the range (or fresh file) — full body.
                            total = length or int(f.get("size") or 0)
                            offset = 0
                            mode = "wb"
                        # SET, never accumulate. The counters used to add the
                        # resume offset and then each chunk, which was right for
                        # a single pass and wrong the moment a retry re-entered
                        # here: the second attempt would add the same first 17 GB
                        # again and the panel would report more downloaded than
                        # the file has. `done_before` is what the earlier FILES
                        # contributed; this file's share is always `downloaded`.
                        with _download_jobs_lock:
                            job["file_bytes_total"] = total
                            job["file_bytes_done"] = offset
                            job["total_bytes_done"] = done_before + offset
                        downloaded = offset
                        with open(tmp_path, mode) as fh:
                            while True:
                                chunk = resp.read(1024 * 1024)
                                if not chunk:
                                    break
                                fh.write(chunk)
                                downloaded += len(chunk)
                                with _download_jobs_lock:
                                    job["file_bytes_done"] = downloaded
                                    job["total_bytes_done"] = done_before + downloaded

                    # Reject a silently truncated stream: HF's CDN sometimes closes the
                    # connection early, leaving a short .gguf that llama.cpp then fails
                    # to load ("tensor ... not within the file bounds").
                    if total > 0 and downloaded != total:
                        raise IOError(
                            f"incomplete download for {f['name']}: got {downloaded} of "
                            f"{total} bytes ({downloaded * 100 // total}%)"
                        )
                    os.replace(tmp_path, dest_path)
                    _drop_manifest(tmp_path)
                except Exception as exc:
                    # KEEP the .part AND its manifest — together they are the
                    # resume point for the next attempt, whether that attempt
                    # comes from this loop or from the interrupted-downloads
                    # list after a restart.
                    grew = (tmp_path.stat().st_size if tmp_path.exists() else 0) > offset
                    if attempt >= _MAX_ATTEMPTS:
                        raise
                    # A wall (auth, a 404, a full disk) fails the same way every
                    # time. Retrying it hides a permanent error behind minutes of
                    # silence, so an attempt that moved NO bytes gets one more
                    # chance and then gives up; one that made progress gets the
                    # full budget, because that is a dropped connection.
                    if not grew and attempt >= 2:
                        raise
                    with _download_jobs_lock:
                        job["status"] = "retrying"
                        job["error"] = f"{type(exc).__name__}: {exc}"
                    time.sleep(_RETRY_BACKOFF[min(attempt - 1, len(_RETRY_BACKOFF) - 1)])
                    with _download_jobs_lock:
                        job["status"] = "running"
                        job["error"] = None
                    continue
                break

        with _download_jobs_lock:
            job["done"] = True
            job["status"] = "done"
            job["finished_at"] = time.time()
    except Exception as exc:
        with _download_jobs_lock:
            job["done"] = True
            job["status"] = "error"
            job["error"] = str(exc)
            job["finished_at"] = time.time()

# A dropped connection is normal on a 20-GB file; a wall is not. Four attempts
# with a widening pause covers the first without turning the second into a long
# silence.
_MAX_ATTEMPTS = 4
_RETRY_BACKOFF = (3, 10, 30)


def _dest_path(f: dict) -> str:
    """Where this file lands, relative to the models directory.

    The DESTINATION is what identifies a download, not the file name: the same
    name lives in a repository twice (two quantisations), and those are two
    different files with two different ".part" streams. Keyed by name, the
    second request handed back the first one's job and the second copy was
    never fetched — with the page reporting success.
    """
    dest_dir = str(f.get("destDir") or "").strip("/")
    name = str(f.get("name") or "")
    return f"{dest_dir}/{name}" if dest_dir else name


def start_hf_download(repo: str, files: list, models_dir: str, token: str) -> str:
    # Idempotence: with a shared "<name>.part" two jobs on the same file set
    # would interleave — if one is already running, hand back its id instead.
    names = sorted(str(f.get("name") or "") for f in files)
    paths = sorted(_dest_path(f) for f in files)
    with _download_jobs_lock:
        for jid, job in _download_jobs.items():
            if (not job.get("done") and job.get("repo") == repo
                    and sorted(job.get("filePaths") or []) == paths):
                return jid
    job_id = secrets_mod.token_hex(8)
    with _download_jobs_lock:
        _download_jobs[job_id] = {
            "status": "running", "done": False, "error": None,
            "repo": repo, "title": repo,
            "created_at": time.time(), "finished_at": None,
            "total_files": len(files),
            "fileNames": names,
            # Exactly where each one lands. The page draws progress on a
            # file's row, and two rows can share one name — matching by name
            # would pick the wrong one.
            "filePaths": paths,
            "total_bytes": sum(f.get("size", 0) for f in files),
            "total_bytes_done": 0,
            "current_idx": 0, "current_file": "", "current_path": "",
            "file_bytes_done": 0, "file_bytes_total": 0,
        }
    threading.Thread(target=_run_download_job,
                     args=(job_id, repo, files, models_dir, token),
                     daemon=True).start()
    return job_id


def _live_part_paths() -> set:
    """Files a running job is actively writing — not orphans, however they look.

    By destination, not by name: a job writing `b/m.gguf` says nothing about a
    partial at `a/m.gguf`, and by name it would claim it — hiding a genuinely
    interrupted download behind someone else's progress.
    """
    with _download_jobs_lock:
        paths = set()
        for job in _download_jobs.values():
            if not job.get("done"):
                paths.update(job.get("filePaths") or [])
        return paths


def scan_interrupted_downloads(models_dir: str) -> list:
    """Partials on disk that no running job owns, as job-shaped rows.

    This is what stops a killed download from reading as a finished one. Each
    row carries the bytes already fetched and, when the manifest survived, is
    resumable in one click.
    """
    now = time.time()
    if (_part_scan_cache["dir"] == models_dir
            and now - _part_scan_cache["at"] < _PART_SCAN_TTL):
        return list(_part_scan_cache["rows"])

    root = Path(models_dir)
    live = _live_part_paths()
    rows = []
    try:
        partials = sorted(root.rglob("*.part"))
    except OSError:
        partials = []
    for tmp_path in partials:
        name = tmp_path.name[:-len(".part")]
        try:
            rel = tmp_path.parent.relative_to(root)
        except ValueError:
            rel = Path(".")
        # Path(".") is the root itself, not a directory literally named ".":
        # the dot can't just be trimmed off the string — a directory is
        # allowed to start with one.
        owner = name if rel == Path(".") else f"{rel.as_posix()}/{name}"
        if owner in live:
            continue
        try:
            done_bytes = tmp_path.stat().st_size
            mtime = tmp_path.stat().st_mtime
        except OSError:
            continue
        meta = {}
        try:
            meta = json.loads(_manifest_path(tmp_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        try:
            dest_dir = str(tmp_path.parent.relative_to(root))
        except ValueError:
            continue
        rows.append({
            "jobId": "part:%s/%s" % (dest_dir, name),
            "status": "interrupted",
            "done": False,
            "error": None,
            "repo": meta.get("repo") or "",
            "title": meta.get("repo") or dest_dir,
            "created_at": meta.get("started_at") or mtime,
            "finished_at": None,
            "total_files": 1,
            "fileNames": [name],
            "filePaths": [f"{dest_dir}/{name}" if dest_dir else name],
            "total_bytes": int(meta.get("size") or 0),
            "total_bytes_done": done_bytes,
            "current_idx": 0,
            "current_file": name,
            "current_path": f"{dest_dir}/{name}" if dest_dir else name,
            "file_bytes_done": done_bytes,
            "file_bytes_total": int(meta.get("size") or 0),
            # Without a manifest the repo and in-repo path are unrecoverable
            # from the filesystem alone, so the row can only be reported.
            "resumable": bool(meta.get("repo") and meta.get("path")),
            "destDir": dest_dir,
        })
    _part_scan_cache.update({"at": now, "dir": models_dir, "rows": rows})
    return list(rows)


def resume_interrupted_download(models_dir: str, token: str,
                                dest_dir: str, name: str) -> str:
    """Re-issue the job for one orphaned partial. Returns its job id."""
    if ".." in dest_dir or dest_dir.startswith("/"):
        raise ValueError("invalid destDir")
    tmp_path = Path(models_dir) / dest_dir / f"{name}.part"
    try:
        meta = json.loads(_manifest_path(tmp_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("no manifest for this partial — cannot tell which repo it came from")
    repo = str(meta.get("repo") or "")
    path = str(meta.get("path") or "")
    if not repo or not path:
        raise ValueError("manifest is missing the repo or file path")
    # start_hf_download resumes from the .part by itself, and its idempotence
    # check hands back the running job if this was pressed twice.
    return start_hf_download(repo, [{
        "path": path,
        "name": name,
        "destDir": dest_dir,
        "size": int(meta.get("size") or 0),
    }], models_dir, token)
