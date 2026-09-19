"""Moving models between stores without losing one on the way.

A move is copy → prove → delete, and only the delete cannot be undone, so
every rule here guards it:

* The copy lands under a temporary name (PART_SUFFIX) and takes its real name
  only after the proof, so a file under its final name in the library is
  always whole. The mover deletes nothing in the library but its own
  temporary copies.
* A move runs in any direction between two stores — this disk into a library,
  a library back onto this disk, one library into another. The rules below are
  about which END is a library, not about which one is the source.
* Neither end that is a library is touched unless its root carries THAT
  library's mark. A share that did not mount leaves an empty local directory
  at the mount point; without the mark a copy would land on the local disk,
  prove itself against itself, and the original would be deleted — and a move
  back would find nothing there and call the file gone.
* The proof is read back FROM THE COPY, past this host's page cache: what was
  just written is still in RAM, and hashing it from there would prove only
  that the RAM is fine (LibraryReader). The copy's sha256 must equal the
  original's, both computed in this run.
* A NAS may acknowledge a write before it is on its disks (an NFS export with
  `async` does exactly that), so a copy that landed in a library holds the
  original for SETTLE_S after its last byte. A copy onto this disk waits for
  nothing: the proof read it back from the disk itself.
* The original is removed only if, at that very moment, the copy still has the
  proven size, the original is the one that was planned (same size, same
  mtime) and no cell has started to use it. Anything else keeps both copies
  and says why.
* An interruption — the NAS drops out, the network blinks, a deploy restarts
  the controller — deletes nothing. The job is written to disk at every step
  and continues from the last point the library confirmed; a library that
  does not answer makes the job WAIT for as long as it takes, not fail.

Only the mover's own thread touches the library: it may block there, and
nothing waits for it. Requests read the job from memory.

An item is a GGUF file, a multi-part GGUF group (which moves whole or not at
all), or a whole model folder — a safetensors checkpoint, a Hugging Face cache.
A folder is walked by the mover in its own thread and travels as one item: its
files are copied and proven, its symlinks are PLANTED rather than followed (a
copy through them would double the bytes of a cache, where every blob also sits
under a link), and its empty directories are recreated. It is removed only once
everything inside is proven, and never if something appeared in it meanwhile.
"""
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from caravan.admin.model_stores import MARKER_NAME, StoreRegistry
from caravan.common.errors import AppError

#: The temporary name a copy carries until it is proven. It does not end in
#: .gguf, so no listing, picker or cell mistakes it for a model.
PART_SUFFIX = ".caravan-part"
#: Read and write in large blocks: at tens of gigabytes, 64 KiB versus 4 MiB is minutes.
CHUNK = 4 * 1024 * 1024
#: How much a copy writes between asking the library to confirm it (fsync).
#: A copy that breaks resumes from the last confirmed point: bytes written
#: after it may have reached the NAS out of order, with a hole before them.
CHECKPOINT_BYTES = 256 * 1024 * 1024
#: Seconds between looks while the library does not answer.
WAIT_S = 30
#: Seconds between the last byte written into the library and the removal of
#: the local copy: time for a NAS that acknowledged early to reach its disks.
SETTLE_S = 120
#: A proof that fails twice on the same file is not a blink of the network.
MAX_ATTEMPTS = 2
#: Failures while the library answers are the file's or this disk's, not an
#: outage; this many of them end the item, both copies where they are.
MAX_ERRORS = 5
#: Room kept free in the library beyond the job's own bytes.
SPACE_MARGIN = 2 * 2 ** 30
#: Finished jobs remembered (on disk and on the page).
KEEP_FINISHED = 20

FINAL_ITEM_STATES = ("done", "skipped", "cancelled")
FINAL_JOB_STATES = ("done", "failed", "cancelled")


class MoveRefused(AppError):
    """A move that is not started, with a reason the page can show."""

    def __init__(self, message, code, status=409):
        super().__init__(message, status)
        self.code = code


class Cancelled(Exception):
    """The operator stopped the job. Raised between blocks, never mid-write."""


class LibraryAbsent(OSError):
    """The library root does not carry this library's mark right now."""


class LibraryReader:
    """Reads a file back from the library past this host's page cache.

    On Linux that is O_DIRECT, through dd, which aligns the buffers O_DIRECT
    demands. Elsewhere — a developer's Mac running the snapshot — there is no
    such flag, and the reader says so: `bypasses_cache` is False, and the job
    records that next to the hash instead of claiming a proof it did not make.
    """

    def __init__(self, direct=None):
        self.bypasses_cache = sys.platform.startswith("linux") if direct is None else bool(direct)

    def chunks(self, path):
        if self.bypasses_cache:
            yield from self._direct(path)
            return
        with open(path, "rb") as fh:
            while True:
                block = fh.read(CHUNK)
                if not block:
                    return
                yield block

    def _direct(self, path):
        proc = subprocess.Popen(["dd", f"if={path}", "iflag=direct", "bs=16M", "status=none"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            while True:
                block = proc.stdout.read(CHUNK)
                if not block:
                    break
                yield block
            err = proc.stderr.read()
            if proc.wait() != 0:
                raise OSError(f"reading back failed: {err.decode(errors='replace').strip()[-200:]}")
        finally:
            if proc.poll() is None:
                # Stopped halfway (a cancel, a mismatch found early): kill dd and
                # reap it aside — it may sit in an NFS wait for a while.
                proc.kill()
                threading.Thread(target=proc.wait, daemon=True).start()


class LocalIo:
    """Every file operation a move performs, in one place, so the snapshot can
    make any one of them fail at the exact byte it wants."""

    def open_read(self, path):
        return open(path, "rb")

    def open_append(self, path):
        return open(path, "ab")

    def size(self, path):
        return os.stat(path).st_size

    def exists(self, path):
        return os.path.exists(path)

    def is_link(self, path):
        return os.path.islink(path)

    def stamp(self, path):
        st = os.stat(path)
        return [st.st_size, st.st_mtime_ns]

    def mark(self, root):
        """The id in the library's mark, or "" when there is none."""
        try:
            with open(os.path.join(root, MARKER_NAME), encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            return ""
        return str(doc.get("id") or "") if isinstance(doc, dict) else ""

    def truncate(self, path, size):
        os.truncate(path, size)

    def set_mtime(self, path, mtime_ns):
        os.utime(path, ns=(mtime_ns, mtime_ns))

    def replace(self, src, dst):
        os.replace(src, dst)

    def unlink(self, path):
        os.unlink(path)

    def makedirs(self, path):
        os.makedirs(path, exist_ok=True)

    def is_dir(self, path):
        return os.path.isdir(path)

    def walk(self, root):
        """Everything inside a folder, once: (kind, path relative to the folder,
        size, link target). kind is "file", "link", "dir" or "other" — and
        "other" is what makes a move refuse, rather than leave it behind."""
        out = []
        for base, dirs, names in os.walk(root):
            here = os.path.relpath(base, root)
            for name in sorted(dirs) + sorted(names):
                full = os.path.join(base, name)
                rel = name if here == "." else os.path.join(here, name)
                if os.path.islink(full):
                    out.append(("link", rel, 0, os.readlink(full)))
                elif os.path.isdir(full):
                    out.append(("dir", rel, 0, ""))
                elif os.path.isfile(full):
                    out.append(("file", rel, os.stat(full).st_size, ""))
                else:
                    out.append(("other", rel, 0, ""))
        return out

    def symlink(self, target, path):
        os.symlink(target, path)

    def rmtree(self, path):
        shutil.rmtree(path)

    def fsync(self, fh):
        fh.flush()
        os.fsync(fh.fileno())


class MoveJob:
    """One move: what goes where and how far it got. Plain data, written to disk
    after every step; the Mover changes it, the page reads its summary.

    Every key an item or a file will ever carry is there from the plan on: the
    page reads a job while the mover changes it, and a key appearing mid-read
    would break the reader, not the mover."""

    def __init__(self, job_id, source, target, items, created_at=0,
                 status="queued", reason="", finished_at=0, cancel=False, then=None):
        # Both ends are stores — {"id", "name", "root", "kind"}, kind "local"
        # or "library" — and a move runs in any direction between them.
        self.id = str(job_id)
        self.source = dict(source or {})
        self.target = dict(target or {})
        self.items = items
        self.created_at = int(created_at)
        self.status = status
        self.reason = reason
        self.finished_at = int(finished_at or 0)
        self.cancel = bool(cancel)
        # What waits for this move. A cell whose model is being brought back
        # starts when the file is here — {"start": {"hostId", "port"}}. It is
        # kept in the manifest and not in memory because the wait can outlive
        # the process that asked for it: the operator pressed Start, closed the
        # tab, and the controller restarted mid-copy.
        self.then = dict(then or {})

    @staticmethod
    def new_item(key, files, folder="", size=0):
        # A folder (a Hugging Face cache, a safetensors checkpoint) moves whole,
        # as one item: `folder` is its path, `size` what the plan measured, and
        # what is inside — the files, the links between them, the empty
        # directories — is found by the mover, in its own thread.
        return {"key": key, "state": "pending", "note": "", "detail": "", "errors": 0, "files": files,
                "folder": folder, "size": int(size), "links": [], "dirs": [], "scanned": False}

    @staticmethod
    def new_file(rel, size, stamp):
        return {"rel": rel, "size": int(size), "stamp": list(stamp), "state": "pending", "phase": "",
                "done": 0, "synced": 0, "attempts": 0, "copiedAt": 0, "sha256": "", "bypassed": False}

    @classmethod
    def from_json(cls, doc):
        items = []
        for raw in doc.get("items") or []:
            item = cls.new_item(raw["key"], [])
            item.update({k: raw[k] for k in item if k in raw and k != "files"})
            for rf in raw.get("files") or []:
                f = cls.new_file(rf["rel"], rf["size"], rf.get("stamp") or [])
                f.update({k: rf[k] for k in f if k in rf})
                item["files"].append(f)
            items.append(item)
        source, target = doc.get("source"), dict(doc.get("target") or {})
        if not source:
            # A record written before moves ran in both directions: the models
            # disk was always the source, a library always the target.
            source = {"id": "local", "name": "", "root": doc.get("localRoot") or "", "kind": "local"}
            target = {**target, "root": doc.get("libraryRoot") or "", "kind": "library"}
        return cls(doc["id"], source, target, items,
                   created_at=doc.get("createdAt") or 0, status=doc.get("status") or "queued",
                   reason=doc.get("reason") or "", finished_at=doc.get("finishedAt") or 0,
                   cancel=doc.get("cancel"), then=doc.get("then"))

    def to_json(self):
        return {"id": self.id, "source": self.source, "target": self.target,
                "items": self.items, "createdAt": self.created_at, "status": self.status,
                "reason": self.reason, "finishedAt": self.finished_at, "cancel": self.cancel,
                "then": self.then}

    @property
    def source_root(self):
        return str(self.source.get("root") or "")

    @property
    def target_root(self):
        return str(self.target.get("root") or "")

    def library_ends(self):
        """The ends that are libraries: their marks are checked before a byte
        moves, and a copy landing in one holds its original for SETTLE_S."""
        return [end for end in (self.source, self.target) if end.get("kind") == "library"]

    @property
    def finished(self):
        return self.status in FINAL_JOB_STATES

    def paths(self):
        """Every path this job holds — a folder by its own path, so a second
        move cannot take it while this one carries it."""
        return ([f["rel"] for item in self.items for f in item["files"]]
                + [item["folder"] for item in self.items if item.get("folder")])

    @staticmethod
    def _work(item, f):
        """How far one file is, out of 2 × its size: the copy is one pass over
        the link, the proof another."""
        size = f["size"]
        if item["state"] in FINAL_ITEM_STATES or f["phase"] in ("proven", "removed"):
            return 2 * size
        if f["phase"] == "copying":
            return min(size, f["done"])
        if f["phase"] == "checking":
            return size + min(size, f["done"])
        return 0

    @staticmethod
    def _settle_left(item, now):
        """Seconds until the item's copies here may be deleted: SETTLE_S after
        its last byte (see Mover._settle). 0 unless every file of the item is
        proven and the item is still open."""
        # A folder that has not been walked yet holds no files at all: nothing
        # is proven there, so there is nothing to count down. "Every file is
        # proven" is true of an empty list, and asking it for the last byte's
        # time is asking max() of nothing.
        if item["state"] in FINAL_ITEM_STATES or not item["files"]:
            return 0
        if any(f["phase"] != "proven" for f in item["files"]):
            return 0
        last = max(int(f.get("copiedAt") or 0) for f in item["files"])
        return max(0, math.ceil(last + SETTLE_S - now))

    @staticmethod
    def _folder_row(item, settle):
        """A folder's one row: the bytes that landed so far, and the pass the
        file being carried right now is in."""
        files = item["files"]
        done = sum(f["size"] if f["phase"] in ("proven", "removed") else f["done"]
                   for f in files if f["phase"] in ("copying", "checking", "proven", "removed"))
        phase = next((f["phase"] for f in files if f["phase"] in ("copying", "checking")), "")
        if not phase and files:
            if all(f["phase"] == "removed" for f in files):
                phase = "removed"
            elif all(f["phase"] in ("proven", "removed") for f in files):
                phase = "proven"
        return {"path": item["folder"], "item": item["state"], "phase": phase, "done": done,
                "size": item["size"] or sum(f["size"] for f in files), "note": item["note"],
                "detail": item["detail"], "removeIn": settle if phase == "proven" else 0}

    def summary(self, now=None):
        """What the page draws: the totals, and one row per file.

        A proven file says how long until the copy here may go — counted here,
        in seconds, so a page on another clock still counts right. Without it
        the page stood at "copy checked" and "100%" for two minutes with
        nothing to say what it waited for."""
        now = time.time() if now is None else now
        rows, work = [], 0
        for item in self.items:
            settle = self._settle_left(item, now)
            for f in item["files"]:
                work += self._work(item, f)
            if item.get("folder"):
                # A folder is ONE row: the page draws the folder the operator
                # picked, not the thousand files a cache holds.
                rows.append(self._folder_row(item, settle))
                continue
            for f in item["files"]:
                rows.append({"path": f["rel"], "item": item["state"], "phase": f["phase"], "done": f["done"],
                             "size": f["size"], "note": item["note"], "detail": item["detail"],
                             "removeIn": settle if f["phase"] == "proven" else 0})
        total = sum(r["size"] for r in rows)
        return {"id": self.id, "source": {"id": self.source.get("id"), "name": self.source.get("name") or ""},
                "target": {"id": self.target.get("id"), "name": self.target.get("name") or ""},
                "status": self.status, "reason": self.reason,
                "createdAt": self.created_at, "finishedAt": self.finished_at,
                "totalBytes": total, "movedBytes": sum(r["size"] for r in rows if r["item"] == "done"),
                "workDone": work, "workTotal": 2 * total,
                "items": len(self.items), "itemsDone": sum(1 for i in self.items if i["state"] == "done"),
                "files": rows}


class MovePlanner:
    """Turns "move these files there" into a job — or into a refusal that says why.

    Everything is checked BEFORE a byte moves: every file is in the store it is
    said to be in and no RUNNING cell is reading it; a picked part brings its
    whole multi-part group; the target is a store that is here and has room; no
    running job holds the file.
    """

    def __init__(self, unused=None, stores=None, io=None, clock=None, library_files=None,
                 refs=None, holders=None):
        self._unused = unused
        self._stores = stores
        self._library_files = library_files
        self._refs = refs
        self._holders = holders
        self.io = io or LocalIo()
        self._clock = clock or time.time

    def _listing(self):
        if self._unused is not None:
            return self._unused()
        from caravan.admin.model_gc import list_unused_models
        return list_unused_models()

    def _store_rows(self):
        if self._stores is not None:
            return self._stores()
        from caravan.admin.model_stores import registry
        return registry().statuses(force=True)

    def _library_rows(self):
        """What the libraries hold, from the last look — the walk itself is a
        child process with a deadline, never this thread."""
        if self._library_files is not None:
            return self._library_files()
        from caravan.admin.model_stores import registry
        return registry().library_files()

    def _referenced(self):
        """Files a cell names right now, by path relative to a models root —
        the same answer whichever store they sit in."""
        if self._refs is not None:
            return set(self._refs())
        from caravan.admin.model_gc import referenced_set
        return referenced_set()

    def _reading(self, rels):
        """The cells reading these files right now. A stopped cell's model may
        travel — its start brings it back — so being NAMED by a cell is not
        enough to hold a file in place; being read is."""
        if self._holders is not None:
            return list(self._holders(rels))
        from caravan.admin.model_gc import holders
        return holders(rels)

    @staticmethod
    def _end(rows, store_id, side):
        row = next((s for s in rows if s.get("id") == store_id), None)
        if not row:
            raise MoveRefused(f"no such store: {store_id}", f"no-{side}", 404)
        return {"id": row["id"], "name": row.get("name") or "", "path": row.get("path") or "",
                "kind": "local" if row.get("role") == "local" else "library",
                "state": row.get("state") or "unknown", "free": row.get("free"), "detail": row.get("detail") or ""}

    def _source_files(self, source):
        """What the source holds, as the plan needs it: path, size, group, and
        whether a cell uses it. For this disk that is the unused-models listing;
        for a library, its last walk plus the same reference check."""
        if source["kind"] == "local":
            listing = self._listing()
            if not listing.get("ok"):
                raise MoveRefused(listing.get("error") or "the models directory is not readable", "no-source")
            return listing.get("files") or [], listing["path"]
        from caravan.admin.model_gc import part_group
        row = next((r for r in self._library_rows() if r.get("id") == source["id"]), None)
        if row is None:
            raise MoveRefused(f"no such library: {source['id']}", "no-source", 404)
        refs = self._referenced()
        groups = {part_group(r) for r in refs}
        files = []
        for f in row.get("files") or []:
            rel = str(f.get("path") or "")
            # A model folder keeps its kind on the way back too: it is one item
            # to the plan, whichever store it is standing in.
            kind = str(f.get("kind") or "")
            files.append({"path": rel, "sizeBytes": int(f.get("size") or 0), "group": part_group(rel),
                          **({"kind": kind} if kind else {}),
                          "referenced": rel in refs or part_group(rel) in groups})
        return files, str(row.get("path") or source["path"])

    def plan(self, paths, target_id, busy=(), source_id=None):
        wanted = [str(p or "").strip().lstrip("/") for p in (paths or [])]
        wanted = [p for p in wanted if p]
        if not wanted:
            raise MoveRefused("nothing to move", "empty", 400)
        rows = self._store_rows()
        source = self._end(rows, source_id or StoreRegistry.LOCAL_ID, "source")
        target = self._end(rows, target_id, "target")
        if source["id"] == target["id"]:
            raise MoveRefused("that is where they already are", "same-store", 400)
        # A store that is not there, or that cannot be written to, cannot give
        # models away either: the move ends by deleting the originals.
        if source["state"] not in ("ok", "low-space"):
            detail = source.get("detail") or ""
            raise MoveRefused(f"the store they sit in is {source['state']}" + (f": {detail}" if detail else ""),
                              "source-" + str(source["state"]))
        files, root = self._source_files(source)
        by_path = {f["path"]: f for f in files}
        keys = []
        for rel in wanted:
            entry = by_path.get(rel)
            if entry is None:
                where = "the models disk" if source["kind"] == "local" else (source["name"] or source["id"])
                raise MoveRefused(f"not in {where}: {rel}", "unknown-file", 404)
            key = entry.get("group") or rel
            if key not in keys:
                keys.append(key)
        busy = set(busy)
        items, total = [], 0
        for key in keys:
            picked = by_path.get(key) or {}
            if picked.get("kind"):
                # A folder moves whole, as one item; its contents are the
                # mover's business.
                if key in busy:
                    raise MoveRefused(f"already moving: {key}", "busy")
                items.append(MoveJob.new_item(key, [], folder=key, size=int(picked.get("sizeBytes") or 0)))
                total += int(picked.get("sizeBytes") or 0)
                continue
            members = sorted((f for f in files if (f.get("group") or f["path"]) == key and not f.get("kind")),
                             key=lambda f: f["path"])
            for m in members:
                if m["path"] in busy:
                    raise MoveRefused(f"already moving: {m['path']}", "busy")
                if source["kind"] == "local" and self.io.is_link(os.path.join(root, m["path"])):
                    # Removing a link frees nothing and leaves its target behind.
                    # Only asked of this disk: a library is not stat'ed here.
                    raise MoveRefused(f"a link, not a file: {m['path']}", "link")
            # A file in a library has no stamp yet — it would be a stat over the
            # network from the thread answering a request. The mover takes it.
            items.append(MoveJob.new_item(key, [
                MoveJob.new_file(m["path"], m["sizeBytes"],
                                 self.io.stamp(os.path.join(root, m["path"])) if source["kind"] == "local" else [])
                for m in members]))
            total += sum(int(m["sizeBytes"] or 0) for m in members)
        # Who is READING what is about to move — asked once, about everything
        # the plan touches. A cell that merely names a file does not hold it:
        # a stopped cell's model travels, and its start brings it back.
        reading = self._reading([f["rel"] for item in items for f in item["files"]]
                                + [item["folder"] for item in items if item.get("folder")])
        if reading:
            raise MoveRefused(f"a running cell reads it: {', '.join(sorted(reading))}", "in-use")
        if target["state"] not in ("ok", "low-space"):
            detail = target.get("detail") or ""
            raise MoveRefused(f"{target['name'] or 'the store'} is {target['state']}" + (f": {detail}" if detail else ""),
                              "target-" + str(target["state"]))
        free = target.get("free")
        if not isinstance(free, (int, float)) or free < total + SPACE_MARGIN:
            raise MoveRefused(f"{target['name'] or 'the store'} has no room: the move needs {total / 2 ** 30:.1f} GB "
                              f"and {SPACE_MARGIN / 2 ** 30:.0f} GB to spare", "no-room")
        return MoveJob("mv-" + uuid.uuid4().hex[:8],
                       {"id": source["id"], "name": source["name"], "root": root, "kind": source["kind"]},
                       {"id": target["id"], "name": target["name"], "root": target["path"], "kind": target["kind"]},
                       items, created_at=self._clock())


class Mover:
    """Runs one job to its end: every item copied, proven, and only then removed here.

    `save` writes the job to disk; `references(rels)` answers whether a cell uses
    any of the files right now; `library_ok()` answers whether the library is
    back. All of it, and the clock, the sleep and the file operations, arrive
    from outside — the snapshot drives this very class."""

    def __init__(self, job, save, reader=None, io=None, references=None, library_ok=None, sleep=None, clock=None,
                 remember=None, forget=None):
        self.job = job
        self.save = save
        self.reader = reader or LibraryReader()
        self.io = io or LocalIo()
        self._references = references
        self._library_ok = library_ok
        self._sleep = sleep or time.sleep
        self._clock = clock or time.time
        # remember(store_id, rel, size, local_path): keeps the header's facts of a
        # file that now lives in the library (library_meta.py). Called while the
        # local copy still exists — the one moment its header is a local read.
        # forget(store_id, rel): drops them again when the file leaves a library.
        self._remember = remember
        self._forget = forget

    def run(self):
        job = self.job
        try:
            if job.cancel:
                raise Cancelled()
            job.status, job.reason = "running", ""
            self.save()
            for item in job.items:
                if item["state"] not in FINAL_ITEM_STATES:
                    self._item(item)
        except Cancelled:
            for item in job.items:
                if item["state"] not in FINAL_ITEM_STATES:
                    self._close(item, "cancelled", "")
            return self._finish("cancelled")
        return self._finish("done")

    def _finish(self, status):
        self.job.status, self.job.reason = status, ""
        self.job.finished_at = int(self._clock())
        self.save()

    def _src(self, f):
        return os.path.join(self.job.source_root, f["rel"])

    def _dst(self, f):
        return os.path.join(self.job.target_root, f["rel"])

    def _check_cancel(self):
        if self.job.cancel:
            raise Cancelled()

    def _item(self, item):
        if item.get("folder") and not item["scanned"] and not self._scan(item):
            return
        for f in item["files"]:
            if f["state"] != "proven" and not self._bring(item, f):
                return
        if item.get("folder"):
            while True:
                try:
                    self._plant(item)
                    break
                except OSError as exc:
                    if not self._trouble(item, exc):
                        return
        if self.job.target.get("kind") == "library":
            # A library may answer a write before its disks hold it. This disk
            # does not, and the proof read the copy back from it.
            self._settle(item)
        while True:
            try:
                self._stores_here()
                why = self._why_keep(item)
                break
            except OSError as exc:
                if not self._trouble(item, exc):
                    return
        if why:
            self._close(item, "skipped", why)
            return
        item["state"] = "removing"
        self.save()
        if item.get("folder"):
            # The whole folder goes at once: what is inside it was proven file
            # by file, and the walk above found nothing else there.
            folder = os.path.join(self.job.source_root, item["folder"])
            try:
                self.io.rmtree(folder)
            except FileNotFoundError:
                pass
            except OSError as exc:
                self._close(item, "skipped", "unlink-failed", str(exc))
                return
            for f in item["files"]:
                f["phase"] = "removed"
            self._prune_dirs(os.path.dirname(folder))
        else:
            for f in item["files"]:
                try:
                    self.io.unlink(self._src(f))
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    self._close(item, "skipped", "unlink-failed", str(exc))
                    return
                f["phase"] = "removed"
                self._prune_dirs(os.path.dirname(self._src(f)))
        self._forget_headers(item)
        self._close(item, "done", "")

    def _scan(self, item):
        """Read the folder once: the files inside it with their stamps, the
        links between them, the directories that hold nothing. Here, in the
        mover's own thread — a cache holds thousands of entries, and a library's
        walk goes over the network. False when the item was closed instead."""
        folder = os.path.join(self.job.source_root, item["folder"])
        while True:
            try:
                self._stores_here()
                found = self.io.walk(folder)
                break
            except FileNotFoundError:
                return self._close(item, "skipped", "local-gone")
            except OSError as exc:
                if not self._trouble(item, exc):
                    return False
        files, links, dirs = [], [], []
        for kind, rel, size, target in found:
            path = f"{item['folder']}/{rel}".replace(os.sep, "/")
            full = os.path.join(folder, rel)
            if kind == "file":
                files.append(MoveJob.new_file(path, size, self.io.stamp(full)))
            elif kind == "link":
                if os.path.isabs(target) or not self._inside(folder, os.path.join(os.path.dirname(full), target)):
                    # A link out of the folder points at nothing once the folder
                    # is elsewhere, and following it would copy a file that is
                    # not ours to move.
                    return self._close(item, "skipped", "link-out", f"{path} → {target}")
                links.append([path, target])
            elif kind == "dir":
                dirs.append(path)
            else:
                # A socket, a device, a pipe: not something a copy can carry,
                # and deleting the folder would take it away.
                return self._close(item, "skipped", "folder-odd", path)
        item["files"], item["links"], item["dirs"], item["scanned"] = files, links, dirs, True
        item["size"] = sum(f["size"] for f in files) or item["size"]
        self.save()
        return True

    @staticmethod
    def _inside(root, path):
        root, path = os.path.normpath(root), os.path.normpath(path)
        return path == root or path.startswith(root + os.sep)

    def _plant(self, item):
        """The folder's shape at the other end: the directories that hold
        nothing and the links between its files. Written once the files are
        proven — a link made earlier would point at a file that is not there."""
        for rel in item["dirs"]:
            self.io.makedirs(os.path.join(self.job.target_root, rel))
        for rel, target in item["links"]:
            path = os.path.join(self.job.target_root, rel)
            if self.io.exists(path) or self.io.is_link(path):
                continue
            self.io.makedirs(os.path.dirname(path))
            self.io.symlink(target, path)

    def _forget_headers(self, item):
        """The file left a library: what its header said is read from the disk
        again, so the remembered copy of it goes."""
        if self._forget is None or self.job.source.get("kind") != "library":
            return
        for f in item["files"]:
            try:
                self._forget(self.job.source.get("id"), f["rel"])
            except Exception:  # noqa: BLE001 - facts for the picker never cost a move
                pass

    def _bring(self, item, f):
        """Copy one file and prove the copy. True when proven; False when the
        item was closed instead."""
        src, final = self._src(f), self._dst(f)
        part = final + PART_SUFFIX
        while True:
            self._check_cancel()
            try:
                if not self.io.exists(src):
                    return self._close(item, "skipped", "local-gone")
                if not f["stamp"]:
                    # A file in a library gets its stamp here: the plan could not
                    # take one without a stat over the network.
                    f["stamp"] = list(self.io.stamp(src))
                    self.save()
                if list(self.io.stamp(src)) != list(f["stamp"]):
                    return self._close(item, "skipped", "local-changed")
                self._stores_here()
                if self.io.exists(final):
                    # Already there: an earlier run renamed it, or the library had
                    # the model before. It is proven or refused — never overwritten.
                    if self._prove(src, final, f):
                        return self._proven(f)
                    return self._close(item, "skipped", "name-taken")
                self.io.makedirs(os.path.dirname(part))
                self._copy(src, part, f)
                if self._prove(src, part, f):
                    self.io.replace(part, final)
                    self._keep_age(final, f)
                    return self._proven(f)
                self._discard(part)
                f["synced"] = 0
                f["attempts"] += 1
                if f["attempts"] >= MAX_ATTEMPTS:
                    return self._close(item, "skipped", "mismatch")
            except OSError as exc:
                if not self._trouble(item, exc):
                    return False

    def _proven(self, f):
        f["state"], f["phase"] = "proven", "proven"
        self.save()
        if self._remember is not None and self.job.target.get("kind") == "library":
            try:
                self._remember(self.job.target.get("id"), f["rel"], f["size"], self._src(f))
            except Exception:  # noqa: BLE001 - facts for the picker never cost a move
                pass
        return True

    def _keep_age(self, final, f):
        """The library copy keeps the original's time: the tree shows a model's
        age, and a move is not a download. Cosmetic — a share that refuses it
        costs the age shown, never the model."""
        try:
            self.io.set_mtime(final, int(f["stamp"][1]))
        except (OSError, IndexError, TypeError, ValueError):
            pass

    def _copy(self, src, part, f):
        size = f["size"]
        offset = self.io.size(part) if self.io.exists(part) else 0
        if offset > f["synced"]:
            # Past the last confirmed point the part may hold a hole: cut it off.
            self.io.truncate(part, f["synced"])
            offset = f["synced"]
        f["phase"], f["done"] = "copying", offset
        self.save()
        since = 0
        with self.io.open_read(src) as reader, self.io.open_append(part) as writer:
            reader.seek(offset)
            while True:
                self._check_cancel()
                block = reader.read(CHUNK)
                if not block:
                    break
                writer.write(block)
                f["done"] += len(block)
                since += len(block)
                if since >= CHECKPOINT_BYTES:
                    self.io.fsync(writer)
                    f["synced"] = f["done"]
                    self.save()
                    since = 0
            self.io.fsync(writer)
        f["synced"] = f["done"]
        f["copiedAt"] = int(self._clock())
        landed = self.io.size(part)
        if landed != size:
            raise OSError(f"the library copy holds {landed} of {size} bytes")

    def _prove(self, src, dst, f):
        f["phase"], f["done"] = "checking", 0
        self.save()
        local, stop = {}, threading.Event()

        def hash_local():
            try:
                digest = hashlib.sha256()
                with self.io.open_read(src) as fh:
                    while not stop.is_set():
                        block = fh.read(CHUNK)
                        if not block:
                            local["sha"] = digest.hexdigest()
                            return
                        digest.update(block)
            except OSError as exc:
                local["error"] = exc

        # Both sides at once: the local disk is several times faster than the
        # link, so the proof costs one pass over the network, not two.
        worker = threading.Thread(target=hash_local, daemon=True)
        worker.start()
        digest, read = hashlib.sha256(), 0
        try:
            for block in self.reader.chunks(dst):
                self._check_cancel()
                digest.update(block)
                read += len(block)
                f["done"] = read
        except BaseException:
            stop.set()
            raise
        worker.join()
        if "error" in local:
            raise local["error"]
        f["sha256"] = local.get("sha", "")
        f["bypassed"] = bool(self.reader.bypasses_cache)
        return read == f["size"] and digest.hexdigest() == f["sha256"]

    def _settle(self, item):
        # A folder can hold no files at all — only links and empty directories.
        # Those are planted, not written, so there is nothing for the library's
        # disks to catch up with and nothing to wait for.
        last = max((f["copiedAt"] for f in item["files"]), default=0)
        while self._clock() - last < SETTLE_S:
            self._check_cancel()
            self._sleep(1)

    def _stores_here(self):
        """Every end that is a library carries its own mark — checked before a
        byte moves in either direction. Without it, a copy would land on the
        local disk under a bare mount point, and a file to bring back would
        look gone."""
        for end in self.job.library_ends():
            root = str(end.get("root") or "")
            found = self.io.mark(root)
            if found != end.get("id"):
                raise LibraryAbsent(f"{root} does not carry this library's mark"
                                    + (f" (it carries {found})" if found else ""))

    def _why_keep(self, item):
        if item.get("folder"):
            # A file that appeared inside the folder after it was read would be
            # deleted with it, unmoved.
            folder = os.path.join(self.job.source_root, item["folder"])
            cut = len(item["folder"]) + 1
            here = {rel.replace(os.sep, "/") for kind, rel, _size, _target in self.io.walk(folder) if kind == "file"}
            if here != {f["rel"][cut:] for f in item["files"]}:
                return "folder-changed"
        for f in item["files"]:
            local = self._src(f)
            if self.io.exists(local) and list(self.io.stamp(local)) != list(f["stamp"]):
                return "local-changed"
            try:
                landed = self.io.size(self._dst(f))
            except FileNotFoundError:
                return "copy-missing"
            if landed != f["size"]:
                return "copy-missing"
        if self._references is not None and self._references([f["rel"] for f in item["files"]]):
            return "in-use"
        return ""

    def _trouble(self, item, exc):
        """An operation failed. A library that does not answer is an outage:
        wait for it, as long as it takes. A library that answers means the
        fault is the file's or this disk's — MAX_ERRORS of those end the item.
        True: try again; False: the item is closed."""
        detail = f"{type(exc).__name__}: {exc}"
        if self._library_ok is None or self._library_ok():
            item["errors"] += 1
            if item["errors"] >= MAX_ERRORS:
                return self._close(item, "skipped", "errors", detail)
        self._wait(detail)
        return True

    def _wait(self, detail):
        job = self.job
        job.status, job.reason = "waiting", detail
        self.save()
        while True:
            for _ in range(WAIT_S):
                self._check_cancel()
                self._sleep(1)
            if self._library_ok is None or self._library_ok():
                break
        job.status, job.reason = "running", ""
        self.save()

    def _close(self, item, state, note, detail=""):
        if state != "done":
            for f in item["files"]:
                if f["state"] != "proven":
                    self._discard(self._dst(f) + PART_SUFFIX)
        item["state"], item["note"], item["detail"] = state, note, detail
        self.save()
        return False

    def _discard(self, path):
        try:
            if self.io.exists(path):
                self.io.unlink(path)
        except OSError:
            pass

    def _prune_dirs(self, folder):
        root = os.path.normpath(self.job.source_root)
        folder = os.path.normpath(folder)
        while folder.startswith(root + os.sep):
            try:
                os.rmdir(folder)
            except OSError:
                return
            folder = os.path.dirname(folder)


def library_answers(job):
    """While a job waits: are its library ends back — here, carrying THEIR mark,
    and the one being written to writable? Asked from a child process with a
    deadline, like every other look."""
    def check():
        from caravan.admin.model_stores import StoreProbe
        for end in job.library_ends():
            look = StoreProbe().look(str(end.get("root") or ""))
            mark = look.get("marker") if isinstance(look.get("marker"), dict) else {}
            if not (look.get("ok") and look.get("exists") and str(mark.get("id")) == str(end.get("id"))):
                return False
            if end is job.target and not look.get("writable"):
                return False
        return True
    return check


def referenced_now(rels):
    """The last-moment guard: a cell that started READING one of these files
    while the copy was travelling. The same rule the plan refused by, asked
    again at the one moment it decides something — just before the copy here
    is deleted."""
    from caravan.admin.model_gc import holders
    return bool(holders(rels))


def remember_header(store_id, rel, size, local_path):
    from caravan.admin.library_meta import library_meta
    return library_meta().remember_file(store_id, rel, size, local_path)


def forget_header(store_id, rel):
    from caravan.admin.library_meta import library_meta
    return library_meta().forget(store_id, rel)


class MoveRunner:
    """The move jobs of this process: their files on disk, one worker, the list
    the page reads. One job at a time — two copies at once would share the same
    link and each take twice as long."""

    def __init__(self, folder, planner=None, make_mover=None, clock=None, then_start=None):
        self.folder = Path(folder)
        self.planner = planner or MovePlanner()
        # What a finished job's `then` intent does. Passed in rather than
        # imported: a cell start reaches back into half the admin package, and
        # the mover must stay a thing that only moves files.
        self._then_start = then_start or _start_cell
        self._make_mover = make_mover or (lambda job, save: Mover(
            job, save, references=referenced_now, library_ok=library_answers(job),
            remember=remember_header, forget=forget_header))
        self._clock = clock or time.time
        self._jobs = {}
        self._lock = threading.Lock()
        self._thread = None
        # The id of the job the worker is running, None between jobs.
        self._current = None

    def _write(self, job):
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.folder / f"{job.id}.json.tmp"
        tmp.write_text(json.dumps(job.to_json()), encoding="utf-8")
        os.replace(tmp, self.folder / f"{job.id}.json")

    def save(self, job):
        with self._lock:
            self._write(job)

    def start(self, paths, target_id, source_id=None, then=None):
        with self._lock:
            busy = {p for j in self._jobs.values() if not j.finished for p in j.paths()}
        job = self.planner.plan(paths, target_id, busy=busy, source_id=source_id)
        job.then = dict(then or {})
        with self._lock:
            self._jobs[job.id] = job
            self._write(job)
        self._ensure_worker()
        return job.summary()

    def resume(self):
        """Pick up what a restart interrupted. Nothing is decided again: the job
        continues exactly as planned, from the point the library confirmed."""
        if not self.folder.is_dir():
            return 0
        waiting = 0
        for path in sorted(self.folder.glob("*.json")):
            try:
                job = MoveJob.from_json(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError, TypeError):
                continue
            with self._lock:
                if job.id in self._jobs:
                    continue
                if not job.finished:
                    # Its worker died with the old process; it runs again when
                    # its turn comes, and until then it is simply in line.
                    job.status, job.reason = "queued", ""
                    waiting += 1
                self._jobs[job.id] = job
        self._prune()
        if waiting:
            self._ensure_worker()
        return waiting

    def cancel(self, job_id):
        with self._lock:
            job = self._jobs.get(str(job_id))
            if job is None:
                raise MoveRefused(f"no such move: {job_id}", "unknown-job", 404)
            if not job.finished:
                job.cancel = True
                if job.status == "queued" and job.id != self._current:
                    # Not started, so there is nothing to undo: it ends now.
                    # Left to the worker, its rows said "in line" after Stop
                    # until every job before it was done (seen live).
                    for item in job.items:
                        if item["state"] not in FINAL_ITEM_STATES:
                            item["state"] = "cancelled"
                    job.status, job.finished_at = "cancelled", int(self._clock())
                self._write(job)
            return job.summary()

    def summaries(self):
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: (-j.created_at, j.id))
            return [j.summary() for j in jobs]

    def _ensure_worker(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._work, name="store-moves", daemon=True)
            self._thread.start()

    def _work(self):
        while True:
            with self._lock:
                open_jobs = [j for j in self._jobs.values() if not j.finished]
                if not open_jobs:
                    self._thread = None
                    return
                job = min(open_jobs, key=lambda j: (j.created_at, j.id))
                # The job the worker holds: cancel() leaves stopping it to the
                # mover, between blocks.
                self._current = job.id
            try:
                self._make_mover(job, lambda job=job: self.save(job)).run()
            except Exception as exc:  # noqa: BLE001 - a job that breaks must not take the worker with it
                job.status, job.reason, job.finished_at = "failed", f"{type(exc).__name__}: {exc}", int(self._clock())
                self.save(job)
            finally:
                with self._lock:
                    self._current = None
            self._keep_promise(job)
            self._prune()

    def _keep_promise(self, job):
        """What was waiting for this move. Only a job that carried everything
        home keeps its promise: a cell started over a half-moved model would
        read a file that is no longer there. A job that was stopped or failed
        leaves the cell where the operator left it — stopped — and its reason
        is already on the page."""
        start = (job.then or {}).get("start")
        if not start or job.status != "done":
            return
        if any(item["state"] != "done" for item in job.items):
            return
        try:
            self._then_start(start)
        except Exception as exc:  # noqa: BLE001 - a failed start must not take the worker down
            job.reason = job.reason or f"the cell did not start: {type(exc).__name__}: {exc}"
            self.save(job)

    def _prune(self):
        with self._lock:
            done = sorted((j for j in self._jobs.values() if j.finished), key=lambda j: (-j.created_at, j.id))
            for job in done[KEEP_FINISHED:]:
                self._jobs.pop(job.id, None)
                try:
                    (self.folder / f"{job.id}.json").unlink()
                except OSError:
                    pass


_RUNNER = None
_RUNNER_LOCK = threading.Lock()


def _start_cell(where):
    """Start the cell a finished move was bringing a model home for."""
    from caravan.admin.cell_ops import server_cell_action
    server_cell_action({"hostId": where.get("hostId"), "port": where.get("port"), "action": "start"})


def runner():
    """The process's one runner: the jobs and their worker live on it."""
    global _RUNNER
    with _RUNNER_LOCK:
        if _RUNNER is None:
            from caravan.admin.paths import STORE_MOVES_DIR
            _RUNNER = MoveRunner(STORE_MOVES_DIR)
        return _RUNNER
