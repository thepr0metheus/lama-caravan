#!/usr/bin/env python3
"""Value snapshot: comparing a local copy to HF by sha256.

Size and date give a guess; the hash gives an answer.
`google_gemma-4-31B-it-Q4_K_M` once differed by 1,760 bytes out of 19.6 GB —
size alone can't say whether that's metadata or weights, and only the hash
settles it.

What's pinned: three outcomes per file (matched, diverged, unreadable) and a
FOURTH — the file has no oid on HF's side: that's "we don't know", not
"matched". Silence where a confirmation belongs is the exact defect this
whole thing exists to fix. Separately: a cache keyed by (path, size, mtime)
— a touched file is recomputed; running again on the same repository returns
the SAME job, not a second pass over the disk; nothing to check is a
refusal, not an empty job that reads as "checked".

Run: python3 scripts/test_hf_verify.py
"""
import hashlib
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import caravan.admin.hf_verify as hv  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def wait(job_id, limit=10.0):
    deadline = time.time() + limit
    while time.time() < deadline:
        job = hv.verify_status(job_id)["job"]
        if job and job["done"]:
            return job
        time.sleep(0.02)
    return hv.verify_status(job_id)["job"]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        good, bad, blank = d / "good.gguf", d / "bad.gguf", d / "no-oid.gguf"
        good.write_bytes(b"weights" * 1000)
        bad.write_bytes(b"other" * 1000)
        blank.write_bytes(b"small")
        good_sha = hashlib.sha256(good.read_bytes()).hexdigest()

        print("хеш и кэш:")
        check(hv.file_sha256(good) == good_sha, "sha256 файла считается верно")
        seen = []
        hv.file_sha256(good, on_progress=lambda n: seen.append(n))
        check(seen == [good.stat().st_size],
              f"второй раз файл не перечитывается — прогресс сразу на весь размер (got {seen})")
        good.write_bytes(b"changed" * 1000)
        # A just-rewritten file's mtime can land on the same second as the old
        # one — the cache key also includes SIZE, so the swap is still caught.
        check(hv.file_sha256(good) == hashlib.sha256(good.read_bytes()).hexdigest(),
              "файл переписали — хеш пересчитан, а не отдан из кэша")
        good.write_bytes(b"weights" * 1000)

        print("сверка репозитория:")
        files = [
            {"name": "good.gguf", "size": good.stat().st_size, "oid": good_sha},
            {"name": "bad.gguf", "size": bad.stat().st_size, "oid": "0" * 64},
            {"name": "no-oid.gguf", "size": blank.stat().st_size, "oid": ""},
            {"name": "not-here.gguf", "size": 10, "oid": "a" * 64},
        ]
        local = {
            "good.gguf": {"size": good.stat().st_size, "mtime": int(good.stat().st_mtime), "path": str(good)},
            "bad.gguf": {"size": bad.stat().st_size, "mtime": int(bad.stat().st_mtime), "path": str(bad)},
            "no-oid.gguf": {"size": blank.stat().st_size, "mtime": int(blank.stat().st_mtime), "path": str(blank)},
        }
        job_id = hv.start_verify("author/repo", files, local)
        job = wait(job_id)
        check(job and job["done"] and not job["error"], f"задание доходит до конца (got {job and job['error']})")
        got = {n: v["state"] for n, v in (job or {}).get("files", {}).items()}
        check(got.get("good.gguf") == "same", f"positive: хеш сошёлся (got {got.get('good.gguf')})")
        check(got.get("bad.gguf") == "differs", f"negative: хеш разошёлся (got {got.get('bad.gguf')})")
        check(got.get("no-oid.gguf") == "unknown",
              f"у файла нет oid на HF → «не знаем», а НЕ «совпало» (got {got.get('no-oid.gguf')})")
        check("not-here.gguf" not in got,
              "файл, которого нет на диске, не сверяется — считать нечего")
        check(job["totalFiles"] == 3 and job["totalBytes"] == sum(
            local[n]["size"] for n in local),
            f"счётчики считают только сверяемое (got {job['totalFiles']}, {job['totalBytes']})")
        check(job["bytesDone"] >= job["totalBytes"],
              f"прогресс доходит до конца (got {job['bytesDone']} из {job['totalBytes']})")
        check(job["files"]["bad.gguf"]["expected"] == "0" * 64
              and job["files"]["bad.gguf"]["sha256"] != "0" * 64,
              "в ответе обе стороны: чего ждали и что получили")

        print("нечитаемый файл:")
        gone = d / "gone.gguf"
        gone.write_bytes(b"x")
        loc2 = {"gone.gguf": {"size": 1, "mtime": int(gone.stat().st_mtime), "path": str(gone)}}
        gone.unlink()
        job2 = wait(hv.start_verify("author/repo2",
                                    [{"name": "gone.gguf", "size": 1, "oid": "b" * 64}], loc2))
        row2 = (job2 or {}).get("files", {}).get("gone.gguf") or {}
        check(row2.get("state") == "unreadable",
              f"файл исчез между списком и чтением → «нечитаем», не «разошёлся» "
              f"(got {row2.get('state')!r})")
        check("error" in row2, "и причина названа")
        check(job2["done"] and not job2["error"],
              "одна нечитаемая строка не роняет всё задание")

        print("повторный запуск и отказы:")
        long_local = dict(local)
        first = hv.start_verify("author/repo3", files, long_local)
        second = hv.start_verify("author/repo3", files, long_local)
        check(first == second or wait(first) is not None,
              "второй запуск на том же репозитории не плодит второй проход по диску")
        try:
            hv.start_verify("author/empty", files, {})
            check(False, "сверять нечего — должен быть отказ")
        except AppError as exc:
            check("on disk" in str(exc), f"сверять нечего — отказ, а не пустое «сверено» ({exc})")
        try:
            hv.start_verify("", files, local)
            check(False, "пустой репозиторий — должен быть отказ")
        except AppError as exc:
            check(exc.status == 400, f"пустой репозиторий — отказ 400 (got {exc.status})")

        print("статус:")
        by_repo = hv.verify_status("", "author/repo")["job"]
        check(by_repo and by_repo["repo"] == "author/repo",
              "статус находится по имени репозитория — страница спрашивает именно так")
        check(hv.verify_status("нет-такого")["job"] is None,
              "нет такого задания — None, а не выдуманное пустое")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("hf-verify snapshots hold")


if __name__ == "__main__":
    main()
