#!/usr/bin/env python3
"""Cancel stops a download — on the server, not only on the page.

The /hf page had a Cancel button that hid the job's row and nothing else: the
thread kept fetching every file, and a reload brought the row back. There was no
way to stop a download at all. POST /api/hf/download/cancel now raises a flag the
transfer checks before each file and after each mebibyte.

Pinned by value: a cancel mid-file ends the job as "cancelled" (no error) and
keeps the bytes with their manifest, so the partial is listed as interrupted and
resumable; the final name is never written; a cancel is not retried like a
dropped connection; a cancel while one file finishes does not start the next; a
cancel before any byte leaves no partial behind; without a cancel the same job
runs to the end. The route: cancels a running job, refuses an unknown or
finished one and a missing id, and the live job list no longer shows the
cancelled job — its partial shows instead.

Run: python3 scripts/test_download_cancel.py
"""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="caravan-cancel-test-"))
os.environ["CARAVAN_DATA_DIR"] = str(_TMP / "data")
os.environ["LLAMA_ADMIN_STATE"] = str(_TMP / "data" / "admin.json")

from caravan.admin import downloads as dl   # noqa: E402
from caravan.admin import routes             # noqa: E402

PASS, FAIL = [], []
MIB = 1024 * 1024
MODELS = _TMP / "models"


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}{'' if cond else '  ' + detail}")


class _Resp:
    """Serves `size` bytes a mebibyte at a time; `on_read(n)` runs before the
    n-th read, which is where a test presses Cancel."""

    def __init__(self, size, on_read):
        self.headers = {"Content-Length": str(size)}
        self.status = 200
        self._buf = io.BytesIO(b"x" * size)
        self._reads = 0
        self._on_read = on_read

    def read(self, n):
        self._reads += 1
        self._on_read(self._reads)
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def run(files, press_at=None):
    """Run one job in this thread. `press_at` = (file index, read number) at
    which Cancel is pressed — read 0 is the moment the connection opens, and a
    press during read n still delivers that read's chunk, as a real transfer
    would; "before" presses it before the job starts."""
    for p in MODELS.rglob("*"):
        if p.is_file():
            p.unlink()
    calls = []
    job_id = "job-under-test"
    with dl._download_jobs_lock:
        dl._download_jobs.clear()
        dl._download_jobs[job_id] = {
            "status": "running", "done": False, "error": None, "repo": "acme/model", "title": "acme/model",
            "total_files": len(files), "filePaths": [f"{f['destDir']}/{f['name']}" for f in files],
            "total_bytes": sum(f["size"] for f in files), "total_bytes_done": 0,
            "current_idx": 0, "current_file": "", "current_path": "", "file_bytes_done": 0, "file_bytes_total": 0,
        }
    if press_at == "before":
        dl.cancel_hf_download(job_id)

    def fake_urlopen(req, timeout=0):
        name = req.full_url.rsplit("/", 1)[-1]
        calls.append(name)
        # By name, not by call count: a retry asks for the same file again.
        index = next(i for i, x in enumerate(files) if x["name"] == name)
        size = files[index]["size"]

        def on_read(n):
            if press_at not in (None, "before") and press_at == (index, n):
                dl.cancel_hf_download(job_id)
        on_read(0)
        return _Resp(size, on_read)

    dl.urllib.request.urlopen = fake_urlopen
    dl._RETRY_BACKOFF = (0, 0, 0)
    dl._run_download_job(job_id, "acme/model", files, str(MODELS), "")
    with dl._download_jobs_lock:
        return dict(dl._download_jobs[job_id]), calls


def f(name, size, dest="m/acme/Q4"):
    return {"name": name, "path": name, "destDir": dest, "size": size}


def main():
    part = MODELS / "m/acme/Q4/a.gguf.part"
    manifest = MODELS / "m/acme/Q4/a.gguf.part.json"
    final = MODELS / "m/acme/Q4/a.gguf"

    print("cancel in the middle of a file:")
    # The page polls the interrupted list every few seconds and the scan is
    # cached for five: prime the cache while nothing is interrupted, so the pin
    # below sees whether the cancel refreshes it.
    MODELS.mkdir(parents=True, exist_ok=True)
    dl.scan_interrupted_downloads(str(MODELS))
    job, calls = run([f("a.gguf", 5 * MIB)], press_at=(0, 3))
    check("the job ends as cancelled, done, with no error",
          (job.get("status"), job.get("done"), job.get("error")) == ("cancelled", True, None), repr(job))
    check("the bytes fetched so far stay as a partial with its manifest",
          part.exists() and part.stat().st_size == 3 * MIB and manifest.exists(),
          f"part={part.exists() and part.stat().st_size} manifest={manifest.exists()}")
    check("negative: the final name is never written", not final.exists())
    check("negative: a cancel is not retried like a dropped connection", calls == ["a.gguf"], repr(calls))
    rows = dl.scan_interrupted_downloads(str(MODELS))
    row = next((r for r in rows if r.get("current_file") == "a.gguf"), {})
    check("the partial is listed as interrupted and resumable at once — not after the scan cache",
          row.get("status") == "interrupted" and row.get("resumable") is True
          and row.get("total_bytes_done") == 3 * MIB, repr(rows))

    print("without a cancel:")
    job, calls = run([f("a.gguf", 5 * MIB)])
    check("negative: the same job runs to the end and lands the file",
          job.get("status") == "done" and final.exists() and final.stat().st_size == 5 * MIB
          and not part.exists() and not manifest.exists(), repr(job))

    print("cancel while one file finishes:")
    two = [f("a.gguf", 2 * MIB), f("b.gguf", 2 * MIB)]
    job, calls = run(two, press_at=(0, 3))
    check("the file that was finishing is kept whole", final.exists() and final.stat().st_size == 2 * MIB)
    check("and the next one is never requested", calls == ["a.gguf"], repr(calls))
    check("negative: nothing of the next file is left on disk",
          not any((MODELS / "m/acme/Q4").glob("b.gguf*")), repr(sorted(p.name for p in (MODELS / "m/acme/Q4").iterdir())))

    print("cancel before a single byte:")
    job, calls = run([f("a.gguf", 5 * MIB)], press_at=(0, 0))
    check("a partial with no bytes leaves no trace — nothing to resume",
          not part.exists() and not manifest.exists(), f"part={part.exists()} manifest={manifest.exists()}")
    job, calls = run([f("a.gguf", 5 * MIB)], press_at="before")
    check("a cancel that arrives before the job starts sends no request", calls == [], repr(calls))

    print("who can be cancelled:")
    check("negative: an unknown job cannot be", dl.cancel_hf_download("nope") is None)
    with dl._download_jobs_lock:
        dl._download_jobs["finished"] = {"status": "done", "done": True}
    check("negative: a finished job cannot be", dl.cancel_hf_download("finished") is None
          and "cancel" not in dl._download_jobs["finished"])

    print("the routes:")

    class _H:
        def __init__(self):
            self.sent = []

        def send_json(self, doc, *a, **kw):
            self.sent.append(doc)

    def post(body):
        h = _H()
        routes._post_api_hf_download_cancel(h, None, body)
        return h.sent[-1]

    with dl._download_jobs_lock:
        dl._download_jobs.clear()
        dl._download_jobs["live"] = {"status": "running", "done": False, "filePaths": []}
    check("POST cancel raises the flag on a running job",
          post({"jobId": "live"}) == {"ok": True, "jobId": "live"} and dl._download_jobs["live"].get("cancel") is True,
          repr(dl._download_jobs["live"]))
    answer = post({"jobId": "nope"})
    check("negative: an unknown job is refused", answer.get("ok") is False and "not found" in answer.get("error", ""), repr(answer))
    answer = post({})
    check("negative: a missing id is refused", answer == {"ok": False, "error": "missing jobId"}, repr(answer))

    routes.models_dir_from_config = lambda config: MODELS
    routes.parse_config = lambda *a, **kw: {}
    # The state a cancel leaves, laid out directly: this pin is about the list,
    # not about the transfer that produced it.
    for p_ in MODELS.rglob("*"):
        if p_.is_file():
            p_.unlink()
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"x" * 1000)
    manifest.write_text(json.dumps({"repo": "acme/model", "path": "a.gguf", "name": "a.gguf", "destDir": "m/acme/Q4", "size": 5000}))
    dl._part_scan_cache["at"] = 0.0
    with dl._download_jobs_lock:
        dl._download_jobs.clear()
        dl._download_jobs["job-under-test"] = {"status": "cancelled", "done": True, "filePaths": ["m/acme/Q4/a.gguf"]}
        dl._download_jobs["running"] = {"status": "running", "done": False, "filePaths": ["x/y.gguf"]}
    h = _H()
    routes._get_api_hf_download_jobs(h, None)
    listed = h.sent[-1].get("jobs") or []
    ids = [j.get("jobId") for j in listed]
    check("the live list drops the cancelled job and shows its partial instead",
          "job-under-test" not in ids and "running" in ids
          and any(j.get("status") == "interrupted" and j.get("current_file") == "a.gguf" for j in listed), json.dumps(ids))

    print()
    if FAIL:
        print(f"download cancel FAILED ({len(FAIL)}):")
        for name in FAIL:
            print("  - " + name)
        return 1
    print(f"download cancel OK: {len(PASS)} checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
