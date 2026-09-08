"""The model watcher: was anything we have re-issued on Hugging Face.

A 2026-09-07 check showed why this is needed: 11 files across 5 repositories
had diverged from what's on HF, and one of them was running in a cell at the
time. There was no way to know — the repository row set a ✓ on a NAME match,
and a re-issued quant keeps the same name.

Three rules the module never departs from:

* IT WILL NEVER DOWNLOAD ANYTHING ITSELF. A re-issued quant isn't always an
  improvement: :22011's new build is 364 MB smaller than the old one, and the
  cell is tuned around the current file (context, VRAM near 95%, a draft
  model). The decision to replace is the operator's, once they've seen the
  divergence.
* Reach the network only with permission. While the checkbox is off, a pass
  does nothing at all: a watcher that quietly knocks outward once a day isn't
  a setting anymore.
* The report stores what was MEASURED, together with when it was measured. A
  report with no timestamp would read as "just checked", and a stale
  "everything matches" would look fresh.

Who reads the report: the on-disk models page and a cell's card on the board.
They share one comparison rule — caravan/common/model_freshness.py.
"""
import os
import time

from caravan.common.daytime import hhmm, minutes_of_day
from caravan.common.model_freshness import compare_file, repo_summary

#: Default time of day — night, when traffic is in nobody's way.
DEFAULT_WATCH_AT = "03:00"


def watch_settings():
    """Three tiers, and each one turns on the one before it.

    * ``check``    — look once a day for a re-issue;
    * ``at``       — WHAT TIME of day to look ("HH:MM", local);
    * ``download`` — download the new build ON TOP OF the working file;
    * ``keepPrev`` — keep the previous build as a `.prev` hard link
      (OFF by default: disk space costs more than a rollback).

    The replacement happens immediately, with no second copy: disk space
    costs more than a rollback (the operator's decision). A running cell
    doesn't flinch either way — it holds the file through mmap, meaning it
    holds the INODE, and keeps serving the weights it loaded until its next
    restart. On the card it gets a "the file on disk is already newer" mark,
    so the restart is a deliberate choice, not a surprise.

    There's no third tier: "download" and "install" became one action.
    """
    from caravan.admin.state import admin_state
    saved = admin_state.get("modelWatch") if isinstance(admin_state.get("modelWatch"), dict) else {}
    return {"check": bool(saved.get("check")), "download": bool(saved.get("download")),
            # A time of day, not an interval. An interval used to count from
            # service start, and the service restarts on every deploy — 29
            # times a day on this fleet — so a day-long countdown never once
            # reached its end: the checkbox was on, and the check never happened.
            "at": _saved_at(saved),
            "lastCheckDay": str(saved.get("lastCheckDay") or ""),
            # Off by default: disk space costs more than a rollback. Whoever
            # wants the opposite turns it on, and the previous build stays
            # behind as a .prev hard link.
            "keepPrev": bool(saved.get("keepPrev")),
            "lastCheckAt": int(saved.get("lastCheckAt") or 0),
            "lastError": saved.get("lastError") or "",
            "lastFetched": saved.get("lastFetched") or []}


def _saved_at(saved):
    try:
        return hhmm(saved.get("at"), DEFAULT_WATCH_AT)
    except Exception:  # noqa: BLE001
        # A corrupted value in the state must not crash the page: show the
        # default, and the next save will fix it.
        return DEFAULT_WATCH_AT


def set_watch_settings(payload, now=None):
    """`now` is injectable for the same reason `model_watch_tick`'s is: half of
    this rule reads the clock, and a snapshot that cannot set it can only be run
    at the hour that happens to agree with it. It did exactly that — the pins
    below the stamping branch passed in the morning and went red after 03:00,
    which made "green" mean "you ran it early enough"."""
    from caravan.admin.state import admin_state, save_admin_state
    saved = dict(admin_state.get("modelWatch") or {})
    body = payload or {}
    saved["check"] = bool(body.get("check"))
    saved["download"] = bool(body.get("download"))
    saved["keepPrev"] = bool(body.get("keepPrev"))
    saved["at"] = hhmm(body.get("at"), _saved_at(saved))
    saved.pop("replace", None)
    # Downloading without checking is not allowed: the lower tier turns on
    # the one above it. Otherwise "update automatically" with "check" off
    # would be a promise nobody is there to keep.
    if saved["download"]:
        saved["check"] = True
    # A freshly saved setting must not fire RETROACTIVELY: a time that has
    # already passed today is marked as done — otherwise turning the checkbox
    # on at 18:00 with the time set to 03:00 would fire the check
    # immediately, which the operator never asked for. A time still AHEAD
    # today is left unmarked: set it 30 minutes out, and it fires in 30 minutes.
    if saved["check"]:
        stamp = now or time.localtime()
        if minutes_of_day(saved["at"]) <= stamp.tm_hour * 60 + stamp.tm_min:
            saved["lastCheckDay"] = time.strftime("%Y-%m-%d", stamp)
        else:
            saved.pop("lastCheckDay", None)
    admin_state["modelWatch"] = saved
    save_admin_state()
    return watch_settings()


#: What a report row is addressed by. A report with a different value (or
#: none) is treated as unchecked: before 1.3.334 rows sat under a file's
#: NAME, and one of two same-named copies got a verdict nobody had measured.
REPORT_KEYS = "path"


#: How long a recomputed local side stays cached (seconds). The report is
#: read by the models page and by EVERY cell row on the board — without a
#: cache that would be fifty-odd stat() calls on every poll.
_LIVE_TTL = 1.0
#: `source` is the EXACT report object the cache was computed from. Time
#: alone isn't enough: a report rewritten within the same second would still
#: return the old one.
_live_cache = {"at": 0.0, "source": None, "report": None}


def freshness_report(now=None):
    """The report: the remote side as measured, the local side as it is right now.

    An empty report means "not checked", and readers must tell that apart
    from "checked, everything matches": in the first case a file has no state
    at all.

    A report taken under the old key also means "not checked". It isn't
    migrated: its rows aren't just named differently — some of them measured
    the wrong file, and renaming would carry that lie forward under a new address.

    Only the REMOTE side ages: finding out about Hugging Face means actually
    going there, and `checkedAt` is about that trip. The local side costs
    nothing to measure, so it's measured on every read. Otherwise a
    just-downloaded file would keep carrying its old verdict and an "update"
    button — exactly what the operator saw on 2026-09-07, after downloading
    the same file twice.
    """
    from caravan.admin.state import admin_state
    saved = admin_state.get("modelFreshness")
    if not isinstance(saved, dict) or saved.get("keys") != REPORT_KEYS:
        return {"checkedAt": 0, "repos": {}}
    stamp = float(now if now is not None else time.time())
    if (_live_cache["report"] is not None and _live_cache["source"] is saved
            and stamp - _live_cache["at"] < _LIVE_TTL):
        return _live_cache["report"]
    repos = saved.get("repos") if isinstance(saved.get("repos"), dict) else {}
    report = {"checkedAt": int(saved.get("checkedAt") or 0),
              "repos": {repo: {**row, "files": _relive(row.get("files") or {})}
                        for repo, row in repos.items()}}
    _live_cache.update({"at": stamp, "source": saved, "report": report})
    return report


def _relive(files):
    """Recompute each row's state against the file that's on disk RIGHT NOW."""
    out = {}
    for key, row in files.items():
        local = _stat_local(row.get("localPath"))
        state, detail = compare_file(local, {"size": row.get("remoteSize"),
                                             "date": row.get("remoteDate")})
        if state == "missing":
            # The file is no longer on disk: a row about it is no longer
            # about anything. Silence here is more honest than a verdict
            # about something that doesn't exist.
            continue
        out[key] = {**row, **detail, "state": state}
    return out


def _stat_local(path):
    if not path:
        return None
    try:
        st = os.stat(str(path))
    except OSError:
        return None
    return {"size": st.st_size, "mtime": int(st.st_mtime)}


def _save_report(report):
    from caravan.admin.state import admin_state, save_admin_state
    admin_state["modelFreshness"] = {**report, "keys": REPORT_KEYS}
    _live_cache.update({"at": 0.0, "source": None, "report": None})
    save_admin_state()


def local_repos():
    """Repositories we have something from: {repo: {path: {...}}}.

    The models directory is shaped as <model>/<author>/<quant>/<file>, and
    repo_id is <author>/<model>. A file sitting shallower than three levels
    doesn't count as belonging to any repository: guessing the author from
    the filename would be making it up.

    The key is the path RELATIVE to the models directory, not the filename. A
    single name can sit in a repository twice: a live check on 2026-09-07
    found the same file in both the `Q5_K_M` and `default` quants of one
    repository. While the key was the name, the copy with the newer mtime
    displaced the other one, which was never checked at all — yet showed its
    neighbor's verdict and an "update" button that wrote into the wrong path.
    The filename stays in the record: checking against HF still has to go by
    it, since there's only one copy there.
    """
    from caravan.admin.config_builder import models_dir_from_config, parse_config
    root = models_dir_from_config(parse_config())
    out: dict = {}
    if not root.is_dir():
        return out
    for path in root.rglob("*.gguf"):
        try:
            rel = path.relative_to(root).parts
        except ValueError:
            continue
        if len(rel) < 3:
            continue
        repo = f"{rel[1]}/{rel[0]}"
        try:
            st = path.stat()
        except OSError:
            continue
        out.setdefault(repo, {})["/".join(rel)] = {
            "size": st.st_size, "mtime": int(st.st_mtime),
            "path": str(path), "name": path.name}
    return out


def check_pass(now=None, force=False):
    """One pass: ask HF about every local repository and record the report.

    `force` means a pressed button, not the schedule: reaching the network on
    a direct request is allowed even with the checkbox off.
    """
    settings = watch_settings()
    if not settings["check"] and not force:
        return {"checked": False, "reason": "auto-check off"}
    from caravan.admin.hf import hf_list_files
    stamp = int(now or time.time())
    repos_out: dict = {}
    errors = []
    for repo, local in sorted(local_repos().items()):
        listing = hf_list_files(repo)
        if not listing.get("ok"):
            # The repository is gated, renamed, or the network is down. This
            # is NOT "matches": the error is recorded, and no file gets a state.
            errors.append(repo)
            repos_out[repo] = {"error": str(listing.get("error") or "unreachable"),
                               "files": {}, "summary": repo_summary([])}
            continue
        remote = {str(f.get("name") or ""): f for f in listing.get("files") or []}
        files = {}
        for key, meta in local.items():
            # There's one copy on HF, we can have several: EACH ONE is
            # checked, each against its own size and date. All they share is
            # the source.
            name = str(meta.get("name") or key.rsplit("/", 1)[-1])
            row = remote.get(name) or {}
            state, detail = compare_file(meta, row)
            if state == "missing":
                continue
            # Where to put it and where to fetch it from — recorded right
            # here. Without this, a file row's "update" button would have to
            # look up the repository by name all over again — guessing at
            # something already known at comparison time.
            files[key] = {"state": state, **detail, "name": name,
                          "localPath": str(meta.get("path") or ""),
                          "remotePath": str(row.get("path") or ""),
                          "repo": repo}
        repos_out[repo] = {"error": "", "files": files,
                           "summary": repo_summary([f["state"] for f in files.values()])}
    report = {"checkedAt": stamp, "repos": repos_out}
    _save_report(report)
    fetched = _autofetch(repos_out, settings) if settings["download"] else []
    from caravan.admin.state import admin_state, save_admin_state
    saved = dict(admin_state.get("modelWatch") or {})
    saved["lastCheckAt"] = stamp
    saved["lastError"] = f"{len(errors)} repo(s) unreachable" if errors else ""
    if settings["download"]:
        saved["lastFetched"] = fetched[:20]
    admin_state["modelWatch"] = saved
    save_admin_state()
    return {"checked": True, "repos": len(repos_out), "unreachable": len(errors),
            "differs": sum(r["summary"]["differs"] for r in repos_out.values()),
            "fetched": fetched}


def _autofetch(repos_out, settings):
    """Replace everything that's diverged with the new build.

    Nothing is placed alongside it: the file is replaced in place. There's no
    intermediate "downloaded but not installed" tier — there used to be, and
    it was removed (2026-09-07): disk space costs more than a rollback, and a
    separate checkbox is what keeps the previous build.

    Each file's error stays with it: running out of room for one model
    doesn't stop the rest from going ahead, and the reason is named. Silently
    skipping it here would read as "nothing to download".
    """
    from caravan.admin.model_staging import start_update
    out = []
    for repo_row in repos_out.values():
        for key, row in (repo_row.get("files") or {}).items():
            if row.get("state") not in ("size", "date"):
                continue
            try:
                start_update(key)
                out.append({"path": key, "result": "fetching"})
            except Exception as exc:  # noqa: BLE001
                # The error stays WITH THE FILE: running out of room for one
                # model doesn't stop the rest from going ahead, and the
                # reason is named.
                out.append({"path": key, "result": str(exc)})
    return out


def _stamp_day(day):
    """Mark this day as done — and only this day."""
    from caravan.admin.state import admin_state, save_admin_state
    saved = dict(admin_state.get("modelWatch") or {})
    saved["lastCheckDay"] = day
    admin_state["modelWatch"] = saved
    save_admin_state()


def model_watch_tick(now=None):
    """Whether it's time to check. Called once a minute by the shared scheduler.

    The condition is simple: today's time has already arrived, and we
    haven't checked today yet. There's no upper bound on the window — unlike
    the scheduled host shutdown, where being late is pointless (the machine
    is already off). Here being late still matters: "didn't check today"
    stays true at nine in the morning if the controller had no power at
    three. Skipping a day just because the machine happened to be off at the
    scheduled minute is the exact defect this was all rebuilt to fix.

    Deduplicated by DATE, not by a flag: a service restart doesn't reset it.
    """
    settings = watch_settings()
    if not settings["check"]:
        return {"fired": False, "reason": "auto-check off"}
    stamp = now or time.localtime()
    today = time.strftime("%Y-%m-%d", stamp)
    if settings.get("lastCheckDay") == today:
        return {"fired": False, "reason": "already checked today"}
    if not settings.get("lastCheckDay"):
        # No record AT ALL — meaning we didn't "miss today", we're on this
        # schedule for the very first time (a caravan update, where the
        # checkbox was already on). Catch-up doesn't belong here: "we weren't
        # running at 03:00" and "we didn't know how to count days until
        # today" are different things, and telling them apart is exactly this
        # condition's job. Otherwise the very first tick after a deploy fires
        # immediately, and with auto-replace on, starts pulling down tens of
        # gigabytes in a minute the operator never chose (this happened in
        # production on 2026-09-07, 18:47).
        _stamp_day(today)
        return {"fired": False, "reason": "first day under the schedule"}
    if minutes_of_day(settings["at"]) > stamp.tm_hour * 60 + stamp.tm_min:
        return {"fired": False, "reason": "not yet"}
    # The date is stamped BEFORE the pass: the pass reaches the network and
    # can take minutes, and the next tick must not start a second one.
    _stamp_day(today)
    out = check_pass(force=True)
    return {"fired": True, "at": settings["at"], **out}
