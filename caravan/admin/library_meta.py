"""What a GGUF file's header says, remembered for files that live in a library.

The picker and the command builder read a model's header: its trained window,
its architecture, a sidecar's draft depth. On this disk that is a cheap local
read. In a library it would be a read over NFS from the controller process,
which this code never does (model_stores.py). So the header is read where it is
cheap — from the local file, just before a move deletes it — and kept here,
keyed by the library and the file's path, and checked against its size.

A file that reached a library some other way (copied by hand) has no entry: its
row in the picker shows no header facts rather than guessed ones.
"""
import json
import os
import threading
from pathlib import Path


class LibraryMeta:
    """The remembered headers, in one JSON file. `read(path)` turns a LOCAL
    file into its runtime facts; it arrives from outside so the snapshot does
    not parse real headers."""

    def __init__(self, path, read=None):
        self.path = Path(path)
        self._read = read
        self._lock = threading.Lock()
        self._doc = None

    def _load(self):
        if self._doc is None:
            try:
                doc = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                doc = {}
            self._doc = doc if isinstance(doc, dict) else {}
        return self._doc

    def lookup(self, store_id, rel, size):
        """The facts for this file, or None — also when the size no longer
        matches: that is another file under the same name."""
        with self._lock:
            hit = self._load().get(f"{store_id}/{rel}")
        if isinstance(hit, dict) and int(hit.get("size", -1)) == int(size):
            return dict(hit.get("meta") or {})
        return None

    def remember(self, store_id, rel, size, meta):
        with self._lock:
            doc = self._load()
            doc[f"{store_id}/{rel}"] = {"size": int(size), "meta": dict(meta or {})}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)

    def forget(self, store_id, rel):
        """Drop what was remembered for this file: it left the library, and its
        header is a local read again. True when there was something to drop."""
        with self._lock:
            doc = self._load()
            if doc.pop(f"{store_id}/{rel}", None) is None:
                return False
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
            return True

    def remember_file(self, store_id, rel, size, local_path):
        """Read the header from the LOCAL copy and keep it. Only a GGUF has one;
        anything else, a header that does not parse, or one that says nothing
        is not remembered — zeros kept as facts would read as a model with no
        window at all."""
        if not str(rel).lower().endswith(".gguf"):
            return False
        try:
            meta = (self._read or _runtime_meta)(local_path)
        except Exception:
            return False
        if not meta:
            return False
        self.remember(store_id, rel, size, meta)
        return True


def _runtime_meta(path):
    """The runtime facts of a local GGUF, or None when its header says nothing.
    A file that only carries the name got every fact at zero, and they were
    kept as if read (seen live: test files of random bytes)."""
    from caravan.admin.models import extract_runtime_meta, read_gguf_metadata_cached
    raw = read_gguf_metadata_cached(Path(path))
    return extract_runtime_meta(raw) if raw else None


_META = None
_META_LOCK = threading.Lock()


def library_meta():
    """The process's one store of remembered headers."""
    global _META
    with _META_LOCK:
        if _META is None:
            from caravan.admin.paths import LIBRARY_META_FILE
            _META = LibraryMeta(LIBRARY_META_FILE)
        return _META
