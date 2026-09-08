"""One rule: what to say about the local copy of a file from Hugging Face.

There used to be one answer — "a file with this name exists". The repository
row set a ✓ and printed the size and date of the file ON HF NEXT TO IT, so the
operator read a single coherent claim about their own file, and it was
actually about someone else's. A 2026-09-07 fleet check found 11 files across
5 repositories that had diverged, including both Qwen3.8-27B builds, one of
which was running in a cell at the time (17,923,394,624 B locally vs.
17,559,178,144 B on HF — a re-issued quant, not a partial download).

The rule lives here because three places look at it: the HF Browser row, the
on-disk models page, and the scheduled watcher. Three copies of the rule
would drift apart exactly the way the filename and its content did.

The states, and why there are five, not two:

* ``missing``  — no local file;
* ``same``     — size matches and the HF date is no newer than ours;
* ``size``     — sizes differ: the content is DEFINITELY different, nothing
                 to guess at;
* ``date``     — same size, but the HF commit is newer than our file: maybe
                 re-uploaded (metadata, chat template), maybe not;
* ``unknown``  — one side is missing data.

``unknown`` is its own state, not "probably same". Turning not-knowing into a
claim was the original defect.
"""

#: States where the copy is NOT equal to what's on HF.
DIFFERS = ("size", "date")


def compare_file(local, remote):
    """(state, details) for one file.

    ``local``  — {"size": int, "mtime": int}, or None if the file is absent.
    ``remote`` — {"size": int, "date": "2026-08-19T…"} as HF reports it.

    Dates arrive as an ISO string, the file's time as epoch seconds; they are
    compared by calendar day. The upload hour and the commit hour are in
    different time zones, and a same-day difference means nothing — but "four
    days later" does.
    """
    if not isinstance(local, dict):
        return "missing", {}
    local_size = int(local.get("size") or 0)
    remote_size = int((remote or {}).get("size") or 0)
    local_day = _day_from_epoch(local.get("mtime"))
    remote_day = str((remote or {}).get("date") or "")[:10]
    detail = {"localSize": local_size, "remoteSize": remote_size,
              "localDate": local_day, "remoteDate": remote_day}
    if not local_size or not remote_size:
        return "unknown", detail
    if local_size != remote_size:
        return "size", detail
    if local_day and remote_day and remote_day > local_day:
        return "date", detail
    if not local_day or not remote_day:
        return "unknown", detail
    return "same", detail


def _day_from_epoch(mtime):
    try:
        seconds = int(mtime)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    import datetime
    return datetime.datetime.fromtimestamp(seconds).strftime("%Y-%m-%d")


def repo_summary(states):
    """Repository rollup: how many files diverged, and how confidently.

    Returns {"differs": n, "bySize": n, "byDate": n, "unknown": n}. A zero in
    ``differs`` is the claim "checked, and matches" — not "not checked": an
    unchecked file counts under ``unknown`` and is reported separately.
    """
    out = {"differs": 0, "bySize": 0, "byDate": 0, "unknown": 0, "same": 0, "missing": 0}
    for state in states:
        if state in DIFFERS:
            out["differs"] += 1
            out["bySize" if state == "size" else "byDate"] += 1
        elif state in out:
            out[state] += 1
    return out
