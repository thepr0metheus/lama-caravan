"""Where a model file lives right now: on this disk, in a library, or nowhere.

The picker, the cell card and the start path all ask the same question, so it
has one answer, here. This disk is looked at directly — it is local. A library
never is: a dead NFS server makes stat() WAIT (see model_stores.py), so what a
library holds comes from the registry's last look, taken by a child process
within the memory period.

A library counts only while it is really there — available, low on space or
read-only. One that is not mounted, not ours or not answering holds nothing
here, whatever its last list said: its files would be a guess.
"""
import os
import re

#: Library states in which its files can be read.
USABLE = ("ok", "low-space", "read-only")
_PART = re.compile(r"^(?P<stem>.+)-\d{5}-of-(?P<n>\d{5})\.gguf$", re.I)


def home_path(value):
    """A cell's models directory as a real path on this host.

    A saved config writes the home directory in two spellings — "~/models" as
    typed, "$HOME/models" as the launch script renderer stores it so the line
    survives double quotes — and both mean the same folder. Expanding only one
    of them made a file that is right here look as though it lived in a library:
    the test asked about a directory literally named "$HOME", found nothing,
    and the cell was started from the library it had just been carried out of.
    Found live, 2026-09-16.
    """
    raw = str(value or "")
    if raw.startswith("$HOME"):
        raw = "~" + raw[len("$HOME"):]
    elif raw.startswith("${HOME}"):
        raw = "~" + raw[len("${HOME}"):]
    return os.path.expanduser(raw)


class Located:
    """One file's answer. `where` is "local", "library" or "missing"; `path` is
    where THIS host reads it — for "missing", where it was expected."""

    def __init__(self, rel, where, path, store=None, size=0):
        self.rel = rel
        self.where = where
        self.path = path
        self.store = store
        self.size = int(size or 0)

    @property
    def in_library(self):
        return self.where == "library"

    def to_json(self):
        doc = {"rel": self.rel, "where": self.where, "path": self.path}
        if self.store:
            doc["store"] = {"id": self.store["id"], "name": self.store["name"]}
        return doc

    def hint(self):
        """This file as offered to a scout: where the controller reads it.

        A scout that has the same file at the same path — the one on the
        controller's own machine, or one that mounts the library there too —
        reads it in place instead of copying it into its cache. The size tells
        the same file from another at that path; a folder (a seamless model)
        says so, since a folder cannot be downloaded. A library file is not
        looked at here — a dead NFS server makes stat() wait — its size comes
        from the library's last listing. None for a file the controller does
        not have.
        """
        if not self.path:
            return None
        doc = {"path": self.path}
        if self.in_library:
            doc["library"] = str((self.store or {}).get("name") or "")
            if self.size:
                doc["size"] = self.size
            return doc
        # A folder reads as "missing" — the locator asks about files — and a
        # seamless model IS a folder; it is here all the same.
        if os.path.isdir(self.path):
            doc["dir"] = True
        elif self.where == "local" and os.path.isfile(self.path):
            doc["size"] = os.path.getsize(self.path)
        else:
            return None
        return doc


class Locations:
    """A snapshot of the libraries' files, taken once and asked many times: the
    picker lists about a hundred files and the board thirty cells, and none of
    them may cost a look at the NAS."""

    def __init__(self, libraries=(), exists=os.path.isfile):
        self._exists = exists
        self._index = {}
        self._copies = []
        # Every library's root, the unusable ones too, with its store when it
        # is usable: a file under an unusable root is one nobody may look at.
        self._roots = []
        for lib in libraries or ():
            if not lib.get("path"):
                continue
            store = {"id": str(lib["id"]), "name": str(lib.get("name") or lib["id"]), "root": str(lib["path"])}
            usable = lib.get("state") in USABLE
            self._roots.append((store["root"].rstrip("/") + "/", store if usable else None))
            if not usable:
                continue
            for f in lib.get("files") or ():
                self._index.setdefault(str(f["path"]), (store, f))
                self._copies.append((str(f["path"]), store, f))

    def locate(self, rel, local_root):
        rel = str(rel or "").strip().lstrip("/")
        if not rel:
            return None
        local = os.path.join(home_path(local_root), rel)
        if self._exists(local):
            return Located(rel, "local", local)
        hit = self._index.get(rel)
        if hit:
            store, f = hit
            return Located(rel, "library", os.path.join(store["root"], rel), store, f.get("size") or 0)
        return Located(rel, "missing", local)

    def library_entries(self):
        """(rel, store, file) for every file a usable library holds, by path."""
        return [(rel, store, f) for rel, (store, f) in sorted(self._index.items())]

    def library_copies(self):
        """(rel, store, file) for every copy in every usable library. A start
        needs one answer — the first library, library_entries() — but a page
        that says where a model is keeps them all: the same file can sit in two."""
        return sorted(self._copies, key=lambda c: (c[0], c[1]["name"]))

    def library_size(self, rel):
        """What the library holds for this file. A multi-part GGUF counts all its
        parts — the same rule the models page and the ≈VRAM badge follow."""
        same = self._same_file(str(rel or ""))
        return sum(int(f.get("size") or 0) for r, (_store, f) in self._index.items() if same(r))

    def library_file(self, path):
        """What a library holds at `path`, a path as this host reads it, by the
        library's last look: (store, bytes), a multi-part GGUF with all its
        parts. None when `path` is in no library. (None, 0) when its library is
        not usable now — nothing is known about the file, and finding out would
        mean asking a NAS that may not answer."""
        path = str(path or "")
        for root, store in self._roots:
            if not path.startswith(root):
                continue
            if store is None:
                return None, 0
            same = self._same_file(path[len(root):])
            return store, sum(int(f.get("size") or 0) for r, s, f in self._copies
                              if s["id"] == store["id"] and same(r))
        return None

    @staticmethod
    def _same_file(rel):
        """A test for the paths that make up `rel`: itself, or every part of it
        when it is a multi-part GGUF."""
        m = _PART.match(os.path.basename(rel))
        if not m:
            return lambda r: r == rel
        folder = os.path.dirname(rel)
        stem = os.path.join(folder, m.group("stem")) if folder else m.group("stem")
        pattern = re.compile(re.escape(stem) + r"-\d{5}-of-" + m.group("n") + r"\.gguf$", re.I)
        return lambda r: bool(pattern.match(r))


def current_locations(wait=False):
    """The live snapshot: the libraries as the registry last measured them — a
    child process with a deadline, reused for 15 s.

    wait=False (the board, the picker) reads the last measurement without
    waiting for a NAS that may not answer; wait=True (a start) measures what is
    stale first. A registry that cannot be asked yields no libraries — the old
    local-only answer — never an error in the middle of a start."""
    try:
        from caravan.admin.model_stores import registry
        return Locations(registry().library_files(wait=wait))
    except Exception:
        return Locations(())
