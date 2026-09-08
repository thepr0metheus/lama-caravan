"""Updating a model file in place — and flagging that a cell is still running
the old one.

The replacement happens ON TOP OF the working file. By default, with no
second copy: disk space costs more than a rollback (the operator's decision,
2026-09-07). The price is named plainly: the old build is already gone from
Hugging Face — it differs precisely because the author rebuilt it — so
without a copy there is nowhere to get the old weights back from. Whoever
needs the rollback more than the space ticks the "keep the previous build"
box: then, before downloading, the old file gets a HARD LINK,
`<file>.gguf.prev` — instant, and without reading seventeen gigabytes.

The asymmetry everything follows from: the NEW build can always be downloaded
again, the OLD one never can. So a rollback is free to discard the new file,
while a replacement with no copy kept is unrecoverable.

Why this is safe for a RUNNING cell. A download writes to `<file>.part` and
finishes with `os.replace` — which changes the NAME, not the bytes. llama.cpp
holds the file through mmap, meaning it holds the inode: a live process keeps
serving the same weights it loaded and never notices the swap. It sees the
new file only on its next start.

Overwriting IN PLACE (opening and writing into the same inode) is off the
table under any circumstances: a live process's mapping would see the bytes
change under it. Nothing here does that — only rename, and only the
downloader performs it.
"""
import shutil
from pathlib import Path

from caravan.common.errors import AppError

#: Free-space margin on top of the size of the file being downloaded. While a
#: download runs, both builds sit on disk: the old one under the working name
#: and the new one in `.part`.
DISK_MARGIN_BYTES = 2 * 1024 ** 3


def free_bytes(path):
    try:
        return shutil.disk_usage(str(Path(path).parent)).free
    except OSError:
        return 0


def check_room(live_path, need_bytes):
    """Whether there's enough room. A refusal comes with numbers, not just
    "no room"."""
    need = int(need_bytes or 0) + DISK_MARGIN_BYTES
    free = free_bytes(live_path)
    if free < need:
        raise AppError(
            f"not enough room: need {need // 2 ** 30} GB "
            f"(new build + {DISK_MARGIN_BYTES // 2 ** 30} GB margin), free {free // 2 ** 30} GB",
            409)
    return {"free": free, "need": need}


#: Suffix for a kept previous build.
PREV_SUFFIX = ".prev"


def prev_path(live_path):
    return Path(str(live_path) + PREV_SUFFIX)


def keep_prev_enabled():
    from caravan.admin.model_watch import watch_settings
    return bool(watch_settings().get("keepPrev"))


def link_prev(live_path):
    """Preserve the current file as a hard link before it gets replaced.

    A link, not a copy: it's the same inode, and nobody reads seventeen
    gigabytes. Done BEFORE the download — after `os.replace` the old name no
    longer exists.
    """
    import os
    live = Path(live_path)
    if not live.is_file():
        return ""
    prev = prev_path(live)
    if prev.exists():
        prev.unlink()
    try:
        os.link(live, prev)
    except OSError:
        # A different filesystem, or links are disallowed: copy for real —
        # losing the only copy of the old build is not an option.
        shutil.copy2(live, prev)
    return str(prev)


def restore_prev(live_path):
    """Restore the previous build. The new file is discarded — it still
    exists on HF."""
    import os
    live = Path(live_path)
    prev = prev_path(live)
    if not prev.is_file():
        raise AppError("no previous build kept for this file", 404)
    os.replace(prev, live)
    return {"ok": True, "restored": str(live)}


def drop_prev(live_path):
    """Delete the kept previous build — frees up its size."""
    prev = prev_path(Path(live_path))
    try:
        size = prev.stat().st_size
    except OSError:
        return {"ok": True, "freed": 0}
    prev.unlink()
    return {"ok": True, "freed": size}


def prev_overview():
    """Where a kept previous build lives: {file path: {prev, prevSize}}."""
    from caravan.admin.model_watch import freshness_report
    out = {}
    for repo_row in (freshness_report().get("repos") or {}).values():
        for key, row in (repo_row.get("files") or {}).items():
            live = str(row.get("localPath") or "")
            if not live:
                continue
            prev = prev_path(live)
            try:
                st = prev.stat()
            except OSError:
                continue
            out[key] = {"prev": str(prev), "prevSize": st.st_size}
    return out


def _row_for(key):
    """The comparison report's row for a file PATH — together with its repository.

    Path, not name: one name sits in a repository twice (the `Q5_K_M` and
    `default` quants), and by name both rows would point at one copy — a
    button on either one would write into the other's file, and the second
    would silently stay stale.

    The key arrives from outside, but nothing is assembled outward from it:
    it's only a dict key, and the on-disk path comes from the REPORT. A path
    made up by the client simply won't be found.
    """
    from caravan.admin.model_watch import freshness_report
    for repo_id, repo_row in (freshness_report().get("repos") or {}).items():
        found = (repo_row.get("files") or {}).get(str(key or ""))
        if found:
            return found, repo_id
    return None, ""


def start_update(key):
    """Download the new build ON TOP OF the working file. Returns the job id.

    Only the file's PATH relative to the models directory arrives from
    outside; the on-disk path, the repository, and the path within it all
    come from the comparison report — the very one that compared these files
    in the first place. So the button can't ask to download something the
    comparison never saw, and can't point at the wrong copy: every copy of a
    given name has its own report row.
    """
    from caravan.admin.config_builder import models_dir_from_config, parse_config
    from caravan.admin.downloads import start_hf_download
    from caravan.admin.state import admin_state

    key = str(key or "").strip()
    row, repo = _row_for(key)
    if not row:
        raise AppError(f"{key}: not in the last freshness report — run a check first", 404)
    if row.get("state") not in ("size", "date"):
        raise AppError(f"{key}: nothing newer to fetch (state {row.get('state')!r})", 409)
    live = Path(str(row.get("localPath") or ""))
    if not live.is_file():
        raise AppError(f"{key}: the local file is gone — re-run the check", 404)
    remote_path = str(row.get("remotePath") or "")
    if not remote_path:
        raise AppError(f"{key}: the report has no path on HF", 409)
    check_room(live, row.get("remoteSize"))
    # The link is made BEFORE the download: after os.replace, the old name
    # already points at the new inode, and there would be nothing left to
    # preserve.
    kept = link_prev(live) if keep_prev_enabled() else ""

    models_dir = models_dir_from_config(parse_config())
    try:
        dest_dir = str(live.parent.relative_to(models_dir))
    except ValueError:
        raise AppError(f"{key}: lives outside the models directory", 409)
    job = start_hf_download(repo, [{
        "path": remote_path,
        # Under the working name. The downloader writes to "<name>.part" and
        # only does os.replace once the file has arrived whole: a partial
        # download never ends up under the .gguf name, and a running cell
        # holds its inode and never flinches.
        "name": live.name,
        "destDir": dest_dir,
        "size": int(row.get("remoteSize") or 0),
    }], str(models_dir), admin_state.get("hfToken") or "")
    return {"ok": True, "jobId": job, "file": key, "path": str(live), "prev": kept}


def live_path_for(key):
    """The working file's path — from the same report as everything else."""
    row, _repo = _row_for(key)
    if not row or not row.get("localPath"):
        raise AppError(f"{key}: not in the last freshness report", 404)
    return str(row["localPath"])
