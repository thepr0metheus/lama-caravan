#!/usr/bin/env python3
"""Value snapshot: how a cell reports that it HAS CRASHED.

systemd brings a crashed cell back up, and a minute later the card is
"running" again — an evening with three crashes in a row looked like smooth
operation on the board (the 2026-09-06 production case: Xid 8, "CUDA error:
the launch timed out"). The fresh-build watcher doesn't catch this by
construction: it only looks near a fresh binary and requires three crashes
in 15 minutes.

What's pinned is the journal PARSE: the count comes from systemd, the time
from the "Main process exited" line, the reason from the last line ABOVE it
that actually says something relevant; the kind of crash is told apart by the
driver's and llama.cpp's own words.

Run: python3 scripts/test_cell_crash.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import systemd_ctl  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


GPU_HANG = """2026-09-06T21:52:05+0400 linux start.sh[2156731]: 8.46.900.000 I slot print_timing: id 0 | task 2443 | n_decoded = 203
2026-09-06T21:52:14+0400 linux start.sh[2156731]: /home/user/llama.cpp/ggml/src/ggml-cuda/ggml-cuda.cu:106: CUDA error
2026-09-06T21:52:14+0400 linux start.sh[2156731]: 8.46.933.879 E CUDA error: the launch timed out and was terminated
2026-09-06T21:52:14+0400 linux start.sh[2156731]: 8.46.933.882 E   current device: 0, in function ggml_backend_cuda_synchronize
2026-09-06T21:52:16+0400 linux systemd[1677]: lama-cell@22011.service: Main process exited, code=dumped, status=6/ABRT
2026-09-06T21:52:26+0400 linux systemd[1677]: lama-cell@22011.service: Scheduled restart job, restart counter is at 3.
"""

OOM = """2026-09-06T10:00:00+0400 linux start.sh[9]: ggml_backend_cuda_buffer_type_alloc_buffer: allocating 22 GiB
2026-09-06T10:00:01+0400 linux start.sh[9]: cudaMalloc failed: out of memory
2026-09-06T10:00:02+0400 linux systemd[1]: lama-cell@22002.service: Main process exited, code=exited, status=1/FAILURE
"""

QUIET = """2026-09-06T10:00:02+0400 linux systemd[1]: lama-cell@22003.service: Main process exited, code=killed, status=15/TERM
"""

NO_EXIT = """2026-09-06T10:00:00+0400 linux start.sh[9]: 0.00.1 I srv llama_server: listening on http://0.0.0.0:22004
"""


def _with_journal(text):
    systemd_ctl.run = lambda *a, **k: {"ok": True, "stdout": text, "stderr": ""}
    systemd_ctl._cell_crash_cache.clear()


def test_crash_note():
    print("разбор падения:")
    _with_journal(GPU_HANG)
    note = systemd_ctl.cell_crash_note(22011, 3)
    check(note["count"] == 3, f"счёт берётся у systemd, а не из журнала (got {note['count']})")
    check(note["at"] == "2026-09-06T21:52:16+0400",
          f"время — у строки «Main process exited» (got {note['at']!r})")
    check(note["kind"] == "gpu-hang", f"вид: зависание карты (got {note['kind']!r})")
    check(note["reason"] == "8.46.933.879 E CUDA error: the launch timed out and was terminated",
          f"причина — слова самой смерти, а не «code=dumped» (got {note['reason']!r})")

    _with_journal(OOM)
    note = systemd_ctl.cell_crash_note(22002, 1)
    check(note["kind"] == "gpu-oom" and "out of memory" in note["reason"],
          f"нехватка памяти отличается от зависания (got {note['kind']!r} {note['reason']!r})")

    _with_journal(QUIET)
    note = systemd_ctl.cell_crash_note(22003, 1)
    check(note["reason"].startswith("lama-cell@22003.service: Main process exited"),
          f"нечего процитировать — цитируется сама строка systemd (got {note['reason']!r})")

    _with_journal(NO_EXIT)
    note = systemd_ctl.cell_crash_note(22004, 1)
    check(note["at"] == "" and note["reason"] == "",
          f"systemd перезапускал, а в журнале за сутки следа нет — пусто, а не выдумка (got {note!r})")

    print("отрицательные:")
    _with_journal(GPU_HANG)
    check(systemd_ctl.cell_crash_note(22011, 0) is None,
          "ноль перезапусков — записи нет вовсе (и журнал не читается)")
    check(systemd_ctl.cell_crash_note(22011, None) is None, "None — тоже ноль")
    check(systemd_ctl.cell_crash_note(22011, "мусор") is None, "мусор вместо числа — ноль")
    calls = []
    systemd_ctl.run = lambda *a, **k: (calls.append(a), {"ok": True, "stdout": GPU_HANG, "stderr": ""})[1]
    systemd_ctl._cell_crash_cache.clear()
    systemd_ctl.cell_crash_note(22011, 3)
    systemd_ctl.cell_crash_note(22011, 3)
    check(len(calls) == 1, f"второй вызов подряд журнал не перечитывает (got {len(calls)})")
    systemd_ctl.cell_crash_note(22011, 4)
    check(len(calls) == 2, "а новое падение (счёт вырос) перечитывает сразу, не дожидаясь TTL")


test_crash_note()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all cell-crash snapshots hold")
