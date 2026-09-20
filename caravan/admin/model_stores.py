"""Model stores: every place models live, and whether each one is really there.

The controller used to know ONE directory. A library on the NAS adds a second
place, and with it two questions the single directory never had to answer:

* WHICH store is this? A path is not an identity. The same NAS folder is
  /Volumes/shared_for_all/... on the operator's Mac, /mnt/lama-caravan-models
  on the controller, and whatever a client mounts it as. So a library carries
  a mark in its root (MARKER_NAME) with an id of its own, and the id is what
  the caravan remembers; the path is only where THIS host finds it.
* Is it really THERE? An unmounted share leaves its mount point behind as an
  empty directory, and an empty directory reads exactly like an empty library:
  zero models, nothing wrong on screen. The mark settles that as well: no
  mark, no library. Absence gets a state of its own (StoreStatus.STATES)
  instead of being drawn as an empty store.

Nothing in THIS process touches a store's root. A dead NFS server does not
make stat() fail, it makes it WAIT, in the kernel, until the mount's timeout:
tens of seconds on a soft mount, forever on a hard one. A request thread
parked there hangs the page, and a few of them hang the whole board. A child
process can be killed at a deadline; a thread inside the kernel cannot. So
every look inside a store (its mark, its free space, its files) happens in
StoreProbe's child, and the page gets "not answering" instead of a spinner
that never ends.
"""
import inspect
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from caravan.common import model_artifacts
from caravan.common.errors import AppError

#: The mark a library carries in its root. Hidden, so it stays out of the way
#: in Finder and out of the listing below.
MARKER_NAME = ".caravan-store.json"
#: Seconds a look inside a store may take before it is "not answering". A soft
#: NFS mount gives up after ~45 s on its own; the page does not wait that long.
PROBE_TIMEOUT_S = 8.0
#: Seconds a measured status is reused. The page redraws after every action,
#: and a trip to the NAS per redraw measures nothing new.
STATUS_TTL_S = 15.0
#: Below this much free space a store is "low on space" — the same line the
#: /models page already draws for the local disk tile.
LOW_SPACE_BYTES = 50 * 2 ** 30
#: How many top-level folders a library lists; past it, the page says how many
#: more there are instead of pretending the list is complete.
LIST_LIMIT = 200
#: How many GGUF files a library names for the tree on /models; past it, the
#: tree says how many more there are.
FILES_LIMIT = 5000

# The child's whole program. Plain Python with no caravan imports: it has to
# start fast and must not need anything the controller's environment loads.
# The one thing it does bring along is the rule that tells a model folder from
# an ordinary one — carried as its own source text, so the library is walked by
# the same lines the models disk is walked by, not by a copy of them.
_CHILD = inspect.getsource(model_artifacts) + r'''
import json, os, sys, time


def out(doc):
    sys.stdout.write(json.dumps(doc))
    sys.stdout.flush()
    os._exit(0)


try:
    cmd, root, args = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
    mark = os.path.join(root, args["marker"])

    def read_mark():
        try:
            with open(mark, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            return None
        return doc if isinstance(doc, dict) and str(doc.get("id") or "").strip() else None

    if not os.path.isdir(root):
        out({"ok": True, "exists": False})
    found = read_mark()
    mounted = os.path.ismount(root)

    if cmd == "claim":
        if found:
            out({"ok": True, "exists": True, "adopted": True, "marker": found})
        if not mounted and not args.get("force"):
            out({"ok": True, "exists": True, "refused": "not-a-mount"})
        doc = {"id": args["id"], "name": args.get("name") or "", "role": "library",
               "createdAt": int(time.time()), "tool": "lama-caravan"}
        tmp = mark + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(doc, indent=2) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, mark)
        except OSError as exc:
            out({"ok": True, "exists": True, "refused": "not-writable", "error": str(exc)})
        out({"ok": True, "exists": True, "adopted": False, "marker": doc})

    st = os.statvfs(root)
    doc = {"ok": True, "exists": True, "mounted": mounted, "marker": found,
           "free": st.f_bavail * st.f_frsize, "total": st.f_blocks * st.f_frsize,
           "writable": os.access(root, os.W_OK)}
    if args.get("list"):
        folders, files, size, ggufs, arts = {}, 0, 0, [], []

        def count(key, n):
            entry = folders.setdefault(key, {"name": key, "bytes": 0, "files": 0})
            entry["bytes"] += n
            entry["files"] += 1

        for base, dirs, names in os.walk(root):
            # Hidden and system folders hold no models: Synology's #recycle and
            # @eaDir, editors' dot-directories.
            dirs[:] = [d for d in dirs if not hidden(d)]
            rel = relative(base, root)
            plain = [n for n in names if not hidden(n)]
            # A model folder — a whisper cache, a checkpoint — is ONE thing
            # here, as it is on the models disk: the walk keeps going through
            # it to weigh it, but nothing inside is named on its own.
            art = None
            for a in arts:
                if rel == a[0] or rel.startswith(a[0] + "/"):
                    art = a
                    break
            if art is None:
                kind = artifact_kind(rel, plain)
                if kind:
                    art = [rel, kind, 0, 0]
                    arts.append(art)
            for name in plain:
                # "._name" is the AppleDouble shadow macOS writes next to every
                # file it copies onto a share: tiny, and it ends in .gguf too —
                # hidden() has already dropped it.
                try:
                    st = os.lstat(os.path.join(base, name))
                except OSError:
                    continue
                if art is not None:
                    # Links weigh nothing: a move plants them, it does not copy
                    # them, and a cache keeps every blob under one of each.
                    if (st.st_mode & 0o170000) == 0o100000:
                        art[2] += st.st_size
                        art[3] = max(art[3], int(st.st_mtime))
                    continue
                if not name.endswith((".gguf", ".safetensors")):
                    continue
                n = st.st_size
                files += 1
                size += n
                count(rel.split("/", 1)[0] if rel else name, n)
                # The tree on /models draws GGUF files one by one; the same
                # walk that counts them names them.
                if name.endswith(".gguf"):
                    ggufs.append([(rel + "/" + name) if rel else name, n, int(st.st_mtime)])
        for rel, kind, n, mtime in arts:
            files += 1
            size += n
            count(rel.split("/", 1)[0], n)
        arts.sort()
        ranked = sorted(folders.values(), key=lambda e: (-e["bytes"], e["name"]))
        limit = int(args.get("limit") or 200)
        ggufs.sort()
        cap = int(args.get("files_limit") or 5000)
        doc.update({"files": files, "bytes": size, "folders": ranked[:limit],
                    "more": max(0, len(ranked) - limit),
                    "entries": ggufs[:cap], "entriesMore": max(0, len(ggufs) - cap),
                    "dirs": [[r, k, n, m] for r, k, n, m in arts[:cap]],
                    "dirsMore": max(0, len(arts) - cap)})
    out(doc)
except Exception as exc:  # noqa: BLE001 - the parent reads one line, whatever broke
    sys.stdout.write(json.dumps({"ok": False, "error": type(exc).__name__ + ": " + str(exc)}))
    sys.stdout.flush()
'''


class StoreRefused(AppError):
    """A store that cannot be added or removed, with a reason the page can act
    on: it offers a second, confirmed try for `not-a-mount` and nothing else."""

    def __init__(self, message, code, status=409):
        super().__init__(message, status)
        self.code = code


class StoreProbe:
    """Looks inside a store from a child process, with a deadline.

    Two questions go through it: `look` (is it there, whose mark does it carry,
    how much room, what is inside) and `claim` (put a mark into a new library).
    Both answer with a dict; the parent never touches the root.

    On a timeout the child is killed and NOT waited for. A process stuck in an
    NFS wait can take until the mount's own timeout to die, and waiting for it
    here would hand that wait straight back to the request thread this class
    exists to protect. A daemon thread reaps it instead.
    """

    def __init__(self, timeout=PROBE_TIMEOUT_S, python=None, spawn=None):
        self.timeout = float(timeout)
        self.python = python or sys.executable
        self._spawn = spawn or subprocess.Popen

    def look(self, root, listing=False, limit=LIST_LIMIT, files_limit=FILES_LIMIT):
        return self._run("probe", root, {"list": bool(listing), "limit": int(limit), "files_limit": int(files_limit)})

    def claim(self, root, store_id, name, force=False):
        return self._run("claim", root, {"id": store_id, "name": name, "force": bool(force)})

    def _run(self, command, root, args):
        argv = [self.python, "-c", _CHILD, command, str(root),
                json.dumps({**args, "marker": MARKER_NAME})]
        try:
            proc = self._spawn(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except OSError as exc:
            return {"ok": False, "error": f"the probe did not start: {exc}"}
        try:
            stdout, stderr = proc.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            threading.Thread(target=proc.wait, daemon=True).start()
            return {"ok": False, "timeout": True, "error": f"no answer in {self.timeout:g} s"}
        try:
            doc = json.loads((stdout or "").strip() or "null")
        except ValueError:
            doc = None
        if isinstance(doc, dict):
            return doc
        last = ((stderr or "").strip().splitlines() or ["the probe printed nothing"])[-1]
        return {"ok": False, "error": last[:300]}


class ModelStore:
    """One place models live: `id` is who it is, `path` is where THIS host
    finds it, `role` is "local" (the controller's own directory) or "library"."""

    def __init__(self, store_id, name, path, role, builtin=False):
        self.id = str(store_id)
        self.name = str(name or "")
        self.path = str(path)
        self.role = role
        self.builtin = bool(builtin)

    def to_json(self):
        return {"id": self.id, "name": self.name, "path": self.path,
                "role": self.role, "builtin": self.builtin}


class MountFacts:
    """Where a path is mounted from, whether that machine answers, and whether
    /etc/fstab names it — asked WITHOUT touching the path itself.

    A library that does not answer was the one case where the card had nothing
    to say and the operator nowhere to look: the NAS changed address, the mount
    hung, and "not answering" was the whole story (2026-09-20). Both questions
    here are safe on a dead share — /proc/self/mountinfo and /etc/fstab are this
    host's own files, and a knock on the server is a connect with its own
    deadline — while a stat() on the mount point is exactly what waits.
    """

    #: The port a source of this kind answers on. A source that names no host —
    #: a local device — is not knocked on at all.
    PORTS = {"nfs": 2049, "nfs4": 2049, "cifs": 445, "smb3": 445}
    KNOCK_TIMEOUT = 1.5

    def __init__(self, mounts="/proc/self/mountinfo", fstab="/etc/fstab", knock=None,
                 timeout=KNOCK_TIMEOUT):
        self.mounts = mounts
        self.fstab = fstab
        self.timeout = float(timeout)
        self._knock = knock or self._connect

    def at(self, path):
        """{"source", "type", "host", "answers", "inFstab"} — or None when this
        host says nothing about `path`. `answers` is None when there is nobody
        to knock on: a local device, or a kind of mount we have no port for."""
        mount = self._mounted(path)
        doc = {"inFstab": self._in_fstab(path)}
        if mount is None:
            return {**doc, "source": "", "type": "", "host": "", "answers": None}
        source, kind = mount
        host = self._host(source)
        port = self.PORTS.get(kind)
        answers = self._knock(host, port) if host and port else None
        return {**doc, "source": source, "type": kind, "host": host, "answers": answers}

    def _mounted(self, path):
        """(source, type) of the LAST thing mounted at `path` — mounts stack, and
        the last one is what a reader gets — or None."""
        want = os.path.normpath(str(path))
        found = None
        try:
            with open(self.mounts, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    left, _, right = line.partition(" - ")
                    fields, rest = left.split(), right.split()
                    if len(fields) < 5 or len(rest) < 2:
                        continue
                    if os.path.normpath(fields[4].replace("\\040", " ")) == want:
                        found = (rest[1], rest[0])
        except OSError:
            return None
        return found

    def _in_fstab(self, path):
        """Whether /etc/fstab names this mount point — "not mounted" reads very
        differently when nothing was ever going to mount it."""
        want = os.path.normpath(str(path))
        try:
            with open(self.fstab, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    row = line.split("#", 1)[0].split()
                    if len(row) >= 2 and os.path.normpath(row[1]) == want:
                        return True
        except OSError:
            return False
        return False

    @staticmethod
    def _host(source):
        """The machine a source names: "host:/export" (NFS), "//host/share"
        (SMB). A device path names nobody."""
        text = str(source or "")
        if text.startswith("//"):
            return text[2:].split("/")[0]
        if ":" in text and not text.startswith("/"):
            return text.split(":", 1)[0]
        return ""

    def _connect(self, host, port):
        import socket
        try:
            with socket.create_connection((host, int(port)), timeout=self.timeout):
                return True
        except OSError:
            return False


class StoreStatus:
    """What was measured about one store, when, and the one word for it.

    STATES, in the order a store is judged — the first that applies wins:

    unknown      — no answer within the deadline, or the probe failed;
    missing      — no such directory;
    not-mounted  — the directory is there, the library is not (no mark);
    foreign      — a DIFFERENT library is mounted at this path;
    read-only    — here, but this host cannot write to it;
    low-space    — here, but below LOW_SPACE_BYTES free;
    ok           — here, writable, room to spare.

    A library that is not mounted, or not ours, carries NO numbers: its free
    space and its contents would be those of whatever sits under the bare
    mount point — the local disk — drawn next to the library's name.
    """

    STATES = ("ok", "low-space", "read-only", "foreign", "not-mounted", "missing", "unknown")

    def __init__(self, state, detail="", checked_at=0, measured=None):
        if state not in self.STATES:
            raise ValueError(f"unknown store state: {state}")
        self.state = state
        self.detail = str(detail or "")
        self.checked_at = int(checked_at)
        self.measured = dict(measured or {})

    @classmethod
    def judge(cls, store, probe, now):
        now = int(now)
        if not isinstance(probe, dict) or not probe.get("ok"):
            return cls("unknown", str((probe or {}).get("error") or "the probe failed"), now)
        if not probe.get("exists"):
            return cls("missing", f"no directory at {store.path}", now)
        mark = probe.get("marker") if isinstance(probe.get("marker"), dict) else None
        if store.role == "library":
            if not mark:
                return cls("not-mounted", "the folder carries no library mark: the share is not mounted here", now)
            if str(mark.get("id")) != store.id:
                return cls("foreign", f"another library is mounted here: {mark.get('name') or mark.get('id')}", now)
        measured = {k: probe.get(k) for k in ("free", "total", "files", "bytes", "folders", "more",
                                              "entries", "entriesMore", "dirs", "dirsMore")
                    if k in probe}
        if not probe.get("writable"):
            return cls("read-only", "this host cannot write here", now, measured)
        free = probe.get("free")
        if isinstance(free, (int, float)) and free < LOW_SPACE_BYTES:
            return cls("low-space", f"{free / 2 ** 30:.1f} GB free", now, measured)
        return cls("ok", "", now, measured)

    def to_json(self):
        doc = {"state": self.state, "detail": self.detail, "checkedAt": self.checked_at}
        for key in ("free", "total", "files", "folders", "more", "mount"):
            if key in self.measured:
                doc[key] = self.measured[key]
        if "bytes" in self.measured:
            doc["size"] = self.measured["bytes"]
        return doc


class StoreRegistry:
    """The stores this controller knows, and a short memory of how each looked.

    The controller's own models directory is always first and is never saved
    here: it is read from the config every time, so the ✎ on the models page
    stays the one place that changes it. The libraries the operator added live
    in admin_state["modelStores"] as {id, name, path}.

    Removing a library takes it off the list and nothing else: its files and
    its mark stay where they are, so adding the same folder back (here, or on
    another host) finds the same library by its mark.

    Everything with side effects arrives through the constructor — the admin
    state and its save, the local directory, the probe, the clock — so the
    snapshot drives this very class with fakes instead of a copy of it.
    """

    LOCAL_ID = "local"

    def __init__(self, state=None, save=None, local_root=None, probe=None, clock=None, ttl=STATUS_TTL_S,
                 mount_facts=None):
        self._state = state
        self._save = save
        self._local_root = local_root
        self.probe = probe or StoreProbe()
        self.mount_facts = mount_facts or MountFacts()
        self._clock = clock or time.time
        self.ttl = float(ttl)
        self._cache = {}
        self._lock = threading.Lock()
        self._refreshing = False

    def _admin(self):
        if self._state is not None:
            return self._state()
        from caravan.admin.state import admin_state
        return admin_state

    def _persist(self):
        if self._save is not None:
            return self._save()
        from caravan.admin.state import save_admin_state
        return save_admin_state()

    def _local(self):
        if self._local_root is not None:
            return str(self._local_root())
        from caravan.admin.config_builder import models_dir_from_config, parse_config
        return str(models_dir_from_config(parse_config()))

    def _saved(self):
        rows = self._admin().get("modelStores")
        if not isinstance(rows, list):
            return []
        return [dict(r) for r in rows if isinstance(r, dict)
                and str(r.get("id") or "").strip() and str(r.get("path") or "").strip()]

    def stores(self):
        local = ModelStore(self.LOCAL_ID, "", self._local(), "local", builtin=True)
        return [local] + [ModelStore(r["id"], r.get("name"), r["path"], "library") for r in self._saved()]

    def statuses(self, force=False):
        """Every store with its latest measurement. Stale ones are measured
        again, side by side: one dead library costs the page one deadline,
        not one deadline per store."""
        stores = self.stores()
        now = self._clock()
        with self._lock:
            stale = [s for s in stores if force or self._stale(s, now)]
        if stale:
            with ThreadPoolExecutor(max_workers=min(4, len(stale))) as pool:
                looks = list(pool.map(lambda s: self.probe.look(s.path, listing=s.role == "library"), stale))
            with self._lock:
                for store, probe in zip(stale, looks):
                    status = StoreStatus.judge(store, probe, now)
                    # Why it does not answer, for the card to say: asked only
                    # when something IS wrong, and only about this host's own
                    # files and a port that either answers or does not.
                    if status.state != "ok":
                        try:
                            status.measured["mount"] = self.mount_facts.at(store.path)
                        except Exception:  # noqa: BLE001
                            pass
                    self._cache[store.id] = (store.path, status, now)
        rows = []
        with self._lock:
            for store in stores:
                hit = self._cache.get(store.id)
                status = hit[1] if hit else StoreStatus("unknown", "not measured yet")
                rows.append({**store.to_json(), **status.to_json()})
        return rows

    def library_files(self, force=False, wait=True):
        """What each library holds — its GGUF files and its model folders — for
        the tree on /models, the picker and the start path.

        They come from the same look that counts them for the panel, so a
        library is walked once per memory period, not once per question. A
        library that is not there — not mounted, another library's mark, not
        answering — names no files and says its state: whatever sits under a
        bare mount point is the local disk, not the library.

        wait=False is for the paths a page polls (the board, the picker): the
        last measurement is read as it is, and a stale one is measured again on
        a thread of its own. A dead NAS costs those polls nothing, not the 8 s
        deadline every 15 s."""
        if wait:
            self.statuses(force=force)
        else:
            self._refresh_behind()
        now = self._clock()
        rows = []
        for store in self.stores():
            if store.role != "library":
                continue
            with self._lock:
                hit = self._cache.get(store.id)
            status = hit[1] if hit and hit[0] == store.path else StoreStatus("unknown", "not measured yet")
            entries = status.measured.get("entries") or []
            # A model folder stands beside the files, told apart by its kind:
            # it is one item to the tree and one item to a move, exactly as it
            # is on the models disk.
            found = [{"path": p, "size": s, "ageDays": int(max(0, now - m) // 86400), "mtime": int(m)}
                     for p, s, m in entries]
            found += [{"path": p, "kind": k, "size": s, "ageDays": int(max(0, now - m) // 86400), "mtime": int(m)}
                      for p, k, s, m in (status.measured.get("dirs") or [])]
            found.sort(key=lambda f: f["path"])
            # The root is where THIS host reads the library — a cell that starts
            # from it needs the whole path, not the library's name.
            rows.append({"id": store.id, "name": store.name or store.id, "state": status.state, "path": store.path,
                         "files": found,
                         "more": int(status.measured.get("entriesMore") or 0)
                                 + int(status.measured.get("dirsMore") or 0)})
        return rows

    def _refresh_behind(self):
        """Measure what is stale on a thread of its own — one at a time."""
        now = self._clock()
        stores = self.stores()
        with self._lock:
            if self._refreshing or not any(self._stale(s, now) for s in stores):
                return
            self._refreshing = True

        def run():
            try:
                self.statuses()
            finally:
                with self._lock:
                    self._refreshing = False
        threading.Thread(target=run, name="store-refresh", daemon=True).start()

    def _stale(self, store, now):
        hit = self._cache.get(store.id)
        # A path that changed makes the old measurement someone else's.
        return hit is None or hit[0] != store.path or now - hit[2] >= self.ttl

    def add(self, path, name="", force=False):
        raw = str(path or "").strip()
        if not raw:
            raise StoreRefused("a path is required", "no-path", 400)
        if not os.path.isabs(raw):
            raise StoreRefused(f"the path must be absolute: {raw}", "not-absolute", 400)
        # normpath, never realpath: resolving symlinks means touching the path,
        # and this process does not touch store roots (see the module docstring).
        root = os.path.normpath(raw)
        for other in [os.path.normpath(self._local())] + [os.path.normpath(r["path"]) for r in self._saved()]:
            if root == other:
                raise StoreRefused(f"{root} is already a store", "duplicate")
            if root.startswith(other.rstrip("/") + "/") or other.startswith(root.rstrip("/") + "/"):
                raise StoreRefused(f"{root} and {other} are nested: every model in the inner one would be counted twice", "nested")
        new_id = "lib-" + uuid.uuid4().hex[:8]
        label = str(name or "").strip() or os.path.basename(root) or root
        answer = self.probe.claim(root, new_id, label, force=force)
        if not answer.get("ok"):
            raise StoreRefused(f"{root} does not answer: {answer.get('error') or 'the probe failed'}", "unreachable", 504)
        if not answer.get("exists"):
            raise StoreRefused(f"no directory at {root}", "missing", 404)
        refused = answer.get("refused")
        if refused == "not-a-mount":
            raise StoreRefused(
                f"{root} is not a mount point and carries no library mark: if the share did not mount, "
                "this is an empty local folder, and marking it would make the local disk pose as the library",
                "not-a-mount")
        if refused:
            raise StoreRefused(f"cannot write the library mark into {root}: {answer.get('error') or refused}", str(refused))
        mark = answer.get("marker") or {}
        store_id = str(mark.get("id") or new_id)
        if any(str(r["id"]) == store_id for r in self._saved()):
            raise StoreRefused(f"this library is already on the list (id {store_id})", "duplicate")
        row = {"id": store_id, "name": str(mark.get("name") or label), "path": root}
        self._admin()["modelStores"] = self._saved() + [row]
        self._persist()
        with self._lock:
            self._cache.pop(store_id, None)
        return {**ModelStore(store_id, row["name"], root, "library").to_json(), "adopted": bool(answer.get("adopted"))}

    def repath(self, store_id, path):
        """Point a library at another path on THIS host — the share moved, or
        its mount point did.

        A library is its mark, not its path: the new folder must carry the same
        mark, or this is a different library and belongs to Add. Every other
        refusal is the one Add gives — absolute, not a duplicate, not nested.
        """
        sid = str(store_id or "").strip()
        if sid == self.LOCAL_ID:
            raise StoreRefused("the controller's own models directory is changed with ✎ on the page", "builtin")
        rows = self._saved()
        row = next((r for r in rows if str(r["id"]) == sid), None)
        if row is None:
            raise StoreRefused(f"no such store: {sid}", "unknown-id", 404)
        raw = str(path or "").strip()
        if not raw:
            raise StoreRefused("a path is required", "no-path", 400)
        if not os.path.isabs(raw):
            raise StoreRefused(f"the path must be absolute: {raw}", "not-absolute", 400)
        root = os.path.normpath(raw)
        if root == os.path.normpath(row["path"]):
            return {"store": dict(row)}
        for other in [os.path.normpath(self._local())] + [os.path.normpath(r["path"]) for r in rows
                                                          if str(r["id"]) != sid]:
            if root == other:
                raise StoreRefused(f"{root} is already a store", "duplicate")
            if root.startswith(other.rstrip("/") + "/") or other.startswith(root.rstrip("/") + "/"):
                raise StoreRefused(f"{root} and {other} are nested: every model in the inner one would be counted twice", "nested")
        answer = self.probe.look(root)
        if not answer.get("ok"):
            raise StoreRefused(f"{root} does not answer: {answer.get('error') or 'the probe failed'}", "unreachable", 504)
        mark = answer.get("marker") if isinstance(answer.get("marker"), dict) else None
        if not mark:
            raise StoreRefused(f"{root} carries no library mark: the share is not mounted there", "not-a-mount")
        if str(mark.get("id")) != sid:
            raise StoreRefused(f"{root} holds another library: {mark.get('name') or mark.get('id')}", "other-library")
        row["path"] = root
        self._admin()["modelStores"] = rows
        self._persist()
        with self._lock:
            self._cache.pop(sid, None)
        return {"store": dict(row)}

    def remove(self, store_id):
        sid = str(store_id or "").strip()
        if sid == self.LOCAL_ID:
            raise StoreRefused("the controller's own models directory is changed with ✎, not removed", "builtin")
        rows = self._saved()
        keep = [r for r in rows if str(r["id"]) != sid]
        if len(keep) == len(rows):
            raise StoreRefused(f"no such store: {sid}", "unknown-id", 404)
        self._admin()["modelStores"] = keep
        self._persist()
        with self._lock:
            self._cache.pop(sid, None)
        return {"removed": sid}


_REGISTRY = None
_REGISTRY_LOCK = threading.Lock()


def registry():
    """The process's one registry: the measurement memory lives on it, so every
    request has to reach the same object."""
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            _REGISTRY = StoreRegistry()
        return _REGISTRY
