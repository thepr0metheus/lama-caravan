#!/usr/bin/env python3
"""Value snapshot: a download the hub refuses for terms not accepted names the page to open
(caravan/admin/hub_access.py, downloads.py).

The incident (2026-10-15): nvidia/personaplex-7b-v1 lists its files to anyone and refuses the files —
HTTP 403 — until the owner of the token accepts its terms on its page. The job waited three seconds,
tried a second time, and ended with `HTTP Error 403: Forbidden`. Nothing said which page to go to.

Pinned, each claim with the answer that would pass it wrongly:
  * a wall of the hub (401, 403) is not retried: ONE request, then the job ends;
  * a wall at a GATED repository gives the job an `access` with the repository's page, the status and
    whether a token is saved at all;
  * a wall at a repository that is not gated, a record the hub did not answer, and every other failure
    give NO `access`: no page is named that does not open the door;
  * the other failures keep what they had (a 404 and a lost connection get their second try).

No network is touched: the hub is a fake that answers by address.

Run: python3 scripts/test_download_access.py
"""
import io
import json
import os
import sys
import tempfile
import time
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="caravan-dl-access-test-"))
os.environ["CARAVAN_DATA_DIR"] = str(_TMP)

from caravan.admin import downloads as dl  # noqa: E402
from caravan.admin.hub_access import HubAccess  # noqa: E402

_fail = []
REPO = "nvidia/personaplex-7b-v1"
FILE = {"name": "model.safetensors", "path": "model.safetensors", "destDir": "persona/nvidia/SAFETENSORS", "size": 100}


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class Hub:
    """What answers urlopen: the repository's record (by its api address) and its file (by its resolve address)."""

    def __init__(self, record, file_status=403, file_error=None):
        self.record, self.file_status, self.file_error = record, file_status, file_error
        self.file_requests = 0
        self.record_requests = []

    def __call__(self, req, timeout=0):
        url = req.full_url
        if "/api/models/" in url:
            self.record_requests.append(req.get_header("Authorization"))
            if self.record is None:
                raise OSError("the hub does not answer")
            body = io.BytesIO(json.dumps(self.record).encode())
            body.headers = {}
            return _Json(body)
        self.file_requests += 1
        if self.file_error:
            raise self.file_error
        raise urllib.error.HTTPError(url, self.file_status, "refused", {}, None)


class _Json:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body.getvalue()


def job_after(hub, token="hf_test"):
    real = dl.urllib.request.urlopen
    dl.urllib.request.urlopen = hub
    dl._RETRY_BACKOFF = (0, 0, 0)
    try:
        for p in (_TMP / "models").rglob("*"):
            if p.is_file():
                p.unlink()
        with dl._download_jobs_lock:
            dl._download_jobs.clear()
        job_id = dl.start_hf_download(REPO, [dict(FILE)], str(_TMP / "models"), token)
        for _ in range(300):
            with dl._download_jobs_lock:
                job = dict(dl._download_jobs[job_id])
            if job.get("done"):
                return job
            time.sleep(0.01)
        return job
    finally:
        dl.urllib.request.urlopen = real


def main():
    print("the pieces:")
    check(HubAccess.page(REPO) == "https://huggingface.co/nvidia/personaplex-7b-v1", "the page of a repository is its address on the hub")
    check(HubAccess.page("a b/c#d") == "https://huggingface.co/a%20b/c%23d", "a repository id is quoted, the slash kept")
    wall = lambda code: urllib.error.HTTPError("https://x", code, "m", {}, None)   # noqa: E731
    check(HubAccess.is_wall(wall(403)) and HubAccess.is_wall(wall(401)), "401 and 403 are the hub's wall")
    check(not HubAccess.is_wall(wall(404)) and not HubAccess.is_wall(wall(500)) and not HubAccess.is_wall(OSError("x")),
          "negative: a 404, a server error and a lost connection are no wall")

    print("a wall at a gated repository:")
    hub = Hub({"id": REPO, "gated": "auto"})
    job = job_after(hub)
    check(job["status"] == "error" and hub.file_requests == 1, f"the job ends after ONE request, no second try (requests: {hub.file_requests}, status {job['status']})")
    check(job.get("access") == {"kind": "gated", "url": "https://huggingface.co/nvidia/personaplex-7b-v1", "repo": REPO,
                                "status": 403, "tokenSet": True},
          f"`access` names the repository's page, the status and that a token is saved (got {job.get('access')})")
    check("403" in str(job.get("error")), f"the error text is still the hub's own words (got {job.get('error')!r})")
    check(hub.record_requests == ["Bearer hf_test"], "the record is read with the operator's token, once")
    manual = job_after(Hub({"id": REPO, "gated": "manual"}))
    check((manual.get("access") or {}).get("kind") == "gated", "a repository gated by hand is gated too")
    no_token = job_after(Hub({"id": REPO, "gated": "auto"}, file_status=401), token="")
    check(no_token.get("access", {}).get("tokenSet") is False and no_token["access"]["status"] == 401,
          f"401 with no token saved: the page is named and `tokenSet` is false (got {no_token.get('access')})")

    print("no page where no page opens the door:")
    open_hub = Hub({"id": REPO, "gated": False})
    open_repo = job_after(open_hub)
    check("access" not in open_repo and open_repo["status"] == "error",
          "negative: a wall at a repository that is not gated names no page (a private one, a token the hub does not know)")
    check(open_hub.file_requests == 1 and "403" in str(open_repo.get("error")),
          "...it is still a wall, so one request, and an error row with the hub's words")
    unknown = job_after(Hub(None))
    check("access" not in unknown, "negative: a record the hub did not answer is unknown, and unknown is not gated")
    odd = job_after(Hub({"id": REPO}))
    check("access" not in odd, "negative: a record that says nothing about a gate is not a gated one")
    lost_hub = Hub({"id": REPO, "gated": "auto"}, file_error=OSError("connection reset"))
    lost = job_after(lost_hub)
    check("access" not in lost and lost_hub.file_requests == 2, f"negative: a lost connection is no wall: two tries, no page (requests {lost_hub.file_requests})")
    missing_hub = Hub({"id": REPO, "gated": "auto"}, file_status=404)
    missing = job_after(missing_hub)
    check("access" not in missing and missing_hub.file_requests == 2, f"negative: a 404 is no wall: two tries, no page (requests {missing_hub.file_requests})")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("download access snapshots hold")


if __name__ == "__main__":
    main()
