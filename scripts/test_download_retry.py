#!/usr/bin/env python3
"""A dropped connection should pause a download, not end it.

Twice in one afternoon HF's CDN cut a large transfer — at 17 of 23 GB and at 18
of 42 — and both times the job went to "error" and stopped there, .part intact,
waiting for a person to notice and press Resume. The resume machinery existed;
nothing but a human ever called it.

The two things worth proving are the two that were wrong: that a retry CONTINUES
from the bytes already on disk, and that the byte counters do not double-count
when it does. A third guards the opposite mistake — a permanent failure must
give up quickly rather than hide behind minutes of quiet retrying.
"""
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="caravan-dl-test-"))
os.environ["CARAVAN_DATA_DIR"] = str(_TMP)

from caravan.admin import downloads as dl   # noqa: E402

PASS, FAIL = [], []
BODY = b"x" * 3000            # the "file" being served


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}{'' if cond else '  ' + detail}")


class _Resp:
    """A response that hands over `give` bytes from `start`, then behaves as
    `after` says: "eof" closes early (the CDN drop), "ok" completes."""

    def __init__(self, start, give, after):
        self.headers = {"Content-Length": str(len(BODY) - start)}
        self.status = 206 if start else 200
        self._buf = io.BytesIO(BODY[start:start + give])
        self._after = after

    def read(self, n):
        chunk = self._buf.read(n)
        if chunk:
            return chunk
        if self._after == "eof":
            raise ConnectionResetError("peer closed the connection")
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def run(script, files=None):
    """Drive one job with a scripted sequence of (give, after) per attempt."""
    calls = []

    def fake_urlopen(req, timeout=0):
        start = 0
        rng = req.headers.get("Range") or req.headers.get("range")
        if rng:
            start = int(str(rng).split("=")[1].split("-")[0])
        calls.append(start)
        give, after = script[min(len(calls) - 1, len(script) - 1)]
        if after == "raise":
            raise OSError("permanently broken")
        return _Resp(start, give, after)

    dl.urllib.request.urlopen = fake_urlopen
    dl._RETRY_BACKOFF = (0, 0, 0)              # no real waiting in a test
    job_id = dl.start_hf_download(
        "acme/model",
        files or [{"name": "m.gguf", "path": "m.gguf", "destDir": "m", "size": len(BODY)}],
        str(_TMP / "models"), "")
    import time
    for _ in range(200):
        with dl._download_jobs_lock:
            job = dict(dl._download_jobs[job_id])
        if job.get("done"):
            break
        time.sleep(0.02)
    return job, calls


def main():
    # 1. Cut once, then complete: the job finishes without anyone pressing Resume,
    #    and the retry asks for the bytes it does NOT have.
    job, calls = run([(1000, "eof"), (99999, "ok")])
    check("a dropped connection is retried, not reported as failure",
          job.get("status") == "done", f"status={job.get('status')} err={job.get('error')}")
    check("the retry resumes from what is on disk", calls == [0, 1000], str(calls))
    check("counters do not double-count across the retry",
          job.get("total_bytes_done") == len(BODY), str(job.get("total_bytes_done")))
    dest = _TMP / "models" / "m" / "m.gguf"
    check("the finished file is whole and correct",
          dest.is_file() and dest.read_bytes() == BODY)
    check("no .part is left behind", not (_TMP / "models" / "m" / "m.gguf.part").exists())

    # 2. Cut twice, then complete — still one job, still resuming forward.
    for p in (_TMP / "models" / "m").glob("*"):
        p.unlink()
    job, calls = run([(500, "eof"), (500, "eof"), (99999, "ok")])
    check("two drops in a row are survived", job.get("status") == "done", str(job.get("status")))
    check("each retry starts later than the last", calls == [0, 500, 1000], str(calls))

    # 3. A wall is not a dropped connection: it must give up fast rather than
    #    spend the whole retry budget pretending.
    for p in (_TMP / "models" / "m").glob("*"):
        p.unlink()
    job, calls = run([(0, "raise")])
    check("a request that never connects fails", job.get("status") == "error")
    check("and gives up after two tries, not four", len(calls) == 2, str(calls))
    check("the failure says what happened", "permanently broken" in (job.get("error") or ""),
          str(job.get("error")))

    # 4. A partial download from a DIFFERENT build is not a resume point.
    #    Auto-update places the file ON TOP OF the working one, and a range
    #    request would glue a new tail onto an old head; the completeness
    #    check compares only the byte count and would let that splice through.
    import json as _json
    part_dir = _TMP / "models" / "m"
    for p in part_dir.glob("*"):
        p.unlink()
    part = part_dir / "m.gguf.part"
    part.write_bytes(b"OLD" * 100)
    (part_dir / "m.gguf.part.json").write_text(_json.dumps({
        "repo": "acme/model", "path": "m.gguf", "name": "m.gguf",
        "destDir": "m", "size": len(BODY) + 12345,      # different size = a different build
    }))
    job, calls = run([(99999, "ok")])
    check("a partial from a DIFFERENT build is discarded, not resumed",
          calls == [0], f"resumed from {calls}")
    check("and the file that lands is the new one, whole",
          (part_dir / "m.gguf").read_bytes() == BODY)

    # 5. A partial of the SAME build is a legitimate resume point — leave it alone.
    for p in part_dir.glob("*"):
        p.unlink()
    part.write_bytes(BODY[:400])
    (part_dir / "m.gguf.part.json").write_text(_json.dumps({
        "repo": "acme/model", "path": "m.gguf", "name": "m.gguf",
        "destDir": "m", "size": len(BODY),
    }))
    job, calls = run([(99999, "ok")])
    check("a partial of the SAME build is still resumed", calls == [400], str(calls))

    # 6. No manifest — whose leftover it is stays unknown. "Probably the
    #    same one" costs a whole model here, so we start from scratch.
    for p in part_dir.glob("*"):
        p.unlink()
    part.write_bytes(b"?" * 700)
    job, calls = run([(99999, "ok")])
    check("a partial with no manifest is discarded", calls == [0], str(calls))

    # 7. Two copies of one name in different directories are TWO different
    #    files. The "already downloading this" check used to compare repo +
    #    NAMES, so a second button press would hand back someone else's job,
    #    and the second file would stay stale while the UI showed green. The
    #    destination directory is part of a file's identity.
    with dl._download_jobs_lock:
        dl._download_jobs["already"] = {
            "status": "running", "done": False, "error": None,
            "repo": "acme/model", "fileNames": ["m.gguf"],
            "filePaths": ["a/m.gguf"],
        }
    same = dl.start_hf_download("acme/model", [
        {"name": "m.gguf", "path": "m.gguf", "destDir": "a", "size": len(BODY)}],
        str(_TMP / "models"), "")
    check("the SAME file twice hands back the running job — one .part, one writer",
          same == "already", f"got {same}")
    other = dl.start_hf_download("acme/model", [
        {"name": "m.gguf", "path": "m.gguf", "destDir": "b", "size": len(BODY)}],
        str(_TMP / "models"), "")
    check("the same NAME in another directory is another file, and gets its own job",
          other != "already", f"got {other}")
    with dl._download_jobs_lock:
        for jid in ("already", other):
            dl._download_jobs.pop(jid, None)

    # 8. A job must name WHERE it's writing to: the page draws progress on a
    #    file's row, and two rows can share one name.
    with dl._download_jobs_lock:
        dl._download_jobs.clear()
    for p_ in (_TMP / "models" / "m").glob("*"):
        p_.unlink()
    job, _calls = run([(99999, "ok")])
    check("a job names the destination of each file, not just its name",
          job.get("filePaths") == ["m/m.gguf"], f"got {job.get('filePaths')!r}")
    check("and which one it is on right now",
          job.get("current_path") == "m/m.gguf", f"got {job.get('current_path')!r}")

    # 9. Whose .part this is. A live job "claims" a file so its partial
    #    doesn't look abandoned — but claims it BY PATH. By name, a job
    #    writing b/m.gguf would claim someone else's leftover in a/, and a
    #    genuinely interrupted download would vanish from the list.
    with dl._download_jobs_lock:
        dl._download_jobs.clear()
        dl._download_jobs["live"] = {"done": False, "repo": "acme/model",
                                     "fileNames": ["m.gguf"], "filePaths": ["b/m.gguf"]}
    import json as _json2
    for sub in ("a", "b"):
        d = _TMP / "models" / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / "m.gguf.part").write_bytes(b"?" * 100)
        (d / "m.gguf.part.json").write_text(_json2.dumps({
            "repo": "acme/model", "path": "m.gguf", "name": "m.gguf",
            "destDir": sub, "size": len(BODY)}))
    dl._part_scan_cache.update({"at": 0, "dir": "", "rows": []})
    seen = sorted(r["filePaths"][0] for r in dl.scan_interrupted_downloads(str(_TMP / "models")))
    check("a partial the live job is NOT writing is still reported as interrupted",
          "a/m.gguf" in seen, f"got {seen}")
    check("and the one it IS writing is not called an orphan",
          "b/m.gguf" not in seen, f"got {seen}")
    with dl._download_jobs_lock:
        dl._download_jobs.clear()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
