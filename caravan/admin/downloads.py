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
            req = urllib.request.Request(url, headers=headers)
            # Stream into a job-unique temp name and os.replace() at the end:
            # a half-written file must never sit under the final .gguf name
            # (the model catalog would list it and a cell could try to load it),
            # and two jobs racing on the same destination must not interleave.
            tmp_path = dest_dir / f"{f['name']}.part-{job_id}"
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    total = int(resp.headers.get("Content-Length") or f.get("size") or 0)
                    with _download_jobs_lock:
                        job["file_bytes_total"] = total
                    downloaded = 0
                    with open(tmp_path, "wb") as fh:
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
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
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
    job_id = secrets_mod.token_hex(8)
    with _download_jobs_lock:
        _download_jobs[job_id] = {
            "status": "running", "done": False, "error": None,
            "repo": repo, "title": repo,
            "created_at": time.time(), "finished_at": None,
            "total_files": len(files),
            "total_bytes": sum(f.get("size", 0) for f in files),
            "total_bytes_done": 0,
            "current_idx": 0, "current_file": "",
            "file_bytes_done": 0, "file_bytes_total": 0,
        }
    threading.Thread(target=_run_download_job,
                     args=(job_id, repo, files, models_dir, token),
                     daemon=True).start()
    return job_id
