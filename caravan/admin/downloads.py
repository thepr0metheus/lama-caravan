"""Background HuggingFace GGUF downloads with per-job progress tracking."""
import os
import secrets as secrets_mod
import threading
import time
import urllib.request
from pathlib import Path


_download_jobs: dict = {}

_download_jobs_lock = threading.Lock()


def _run_download_job(job_id: str, repo: str, files: list, models_dir: str, token: str):
    job = _download_jobs[job_id]
    try:
        for i, f in enumerate(files):
            with _download_jobs_lock:
                job["current_idx"] = i
                job["current_file"] = f["name"]
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
            offset = tmp_path.stat().st_size if tmp_path.exists() else 0
            if offset:
                headers["Range"] = f"bytes={offset}-"
            req = urllib.request.Request(url, headers=headers)
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
                    with _download_jobs_lock:
                        job["file_bytes_total"] = total
                        job["file_bytes_done"] = offset
                        job["total_bytes_done"] += offset
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
                                job["total_bytes_done"] += len(chunk)

                # Reject a silently truncated stream: HF's CDN sometimes closes the
                # connection early, leaving a short .gguf that llama.cpp then fails
                # to load ("tensor ... not within the file bounds").
                if total > 0 and downloaded != total:
                    raise IOError(
                        f"incomplete download for {f['name']}: got {downloaded} of "
                        f"{total} bytes ({downloaded * 100 // total}%)"
                    )
                os.replace(tmp_path, dest_path)
            except Exception:
                # KEEP the .part — it is the resume point for the next attempt.
                raise

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

def start_hf_download(repo: str, files: list, models_dir: str, token: str) -> str:
    # Idempotence: with a shared "<name>.part" two jobs on the same file set
    # would interleave — if one is already running, hand back its id instead.
    names = sorted(str(f.get("name") or "") for f in files)
    with _download_jobs_lock:
        for jid, job in _download_jobs.items():
            if (not job.get("done") and job.get("repo") == repo
                    and sorted(job.get("fileNames") or []) == names):
                return jid
    job_id = secrets_mod.token_hex(8)
    with _download_jobs_lock:
        _download_jobs[job_id] = {
            "status": "running", "done": False, "error": None,
            "repo": repo, "title": repo,
            "created_at": time.time(), "finished_at": None,
            "total_files": len(files),
            "fileNames": names,
            "total_bytes": sum(f.get("size", 0) for f in files),
            "total_bytes_done": 0,
            "current_idx": 0, "current_file": "",
            "file_bytes_done": 0, "file_bytes_total": 0,
        }
    threading.Thread(target=_run_download_job,
                     args=(job_id, repo, files, models_dir, token),
                     daemon=True).start()
    return job_id
