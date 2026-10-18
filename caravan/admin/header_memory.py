"""What the headers of GGUF files said, kept in memory and, from one start to the next, on disk.

The header of a file that has not changed does not change: its architecture, its trained window, its layers are
what they were. The controller read them again at every start of its process, and the first /api/state of the
board waited for all of them (51 s for the 56 models of the NAS, 2026-10-14: the owner's red "did not finish
loading"). A header is now read once per file as it is — its path, the second it was written, its size — and the
reading is kept in a file under `state/` (`GGUF_HEADERS_FILE`), so a restart finds the facts of every model it has
seen, and reads only a file that is new or was rewritten.

What a header said is kept only when it said something. A file that says nothing (a download that has not reached
its header, a file that is no GGUF) is remembered in the process, so one walk does not read it twice, but not on
disk: the next start reads it again, and by then it may say something. A fact kept is the one that was read; the
file that holds them is a copy that can be deleted, and the next walk makes it again.
"""
import json
import threading
from pathlib import Path

from caravan.common.fsio import atomic_write_text


class HeaderMemory:
    #: The shape of the file; another number is a file this code did not write, and is not read.
    FORMAT = 1
    #: As many files as the file keeps; past it the ones remembered longest ago go. A library has a hundred models.
    CAP = 4000

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        # file path -> (second written, size, what the header said), in the order of remembering.
        self._files = None
        self._dirty = False
        self._said_no = False

    def _load(self):
        """The remembered files, read from disk the first time. Under the lock."""
        if self._files is None:
            self._files = {}
            try:
                doc = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                doc = None
            files = doc.get("files") if isinstance(doc, dict) and doc.get("format") == self.FORMAT else None
            for name, entry in (files.items() if isinstance(files, dict) else ()):
                # An entry that says nothing is not an entry. One with a second or size of the wrong kind is kept
                # as it is: it can never equal the second and size of a file, so it never answers, and the file is read.
                meta = entry.get("meta") if isinstance(entry, dict) else None
                if isinstance(meta, dict) and meta:
                    self._files[name] = (entry.get("mtime"), entry.get("size"), meta)
        return self._files

    def recall(self, path, mtime, size):
        """What the header of this file said when the file was as it is now (written at `mtime`, `size` long), or None.
        Another time or size is another file under the same name."""
        with self._lock:
            hit = self._load().get(str(path))
        if hit is not None and hit[0] == mtime and hit[1] == size:
            return hit[2]
        return None

    def remember(self, path, mtime, size, meta):
        """Keep what the header of this file said. `{}` is kept in the process only; it never reaches the disk."""
        with self._lock:
            files = self._load()
            before = files.pop(str(path), None)
            files[str(path)] = (mtime, size, meta)
            if meta or (before is not None and before[2]):
                self._dirty = True

    def flush(self):
        """Write the file if something was remembered since it was written. True when it was written. A disk that
        cannot be written to does not stop the controller: it says so once and the facts are read again at the next start."""
        with self._lock:
            if not self._dirty:
                return False
            kept = [(name, entry) for name, entry in self._load().items() if entry[2]]
            doc = {"format": self.FORMAT, "files": {
                name: {"mtime": mtime, "size": size, "meta": meta} for name, (mtime, size, meta) in kept[-self.CAP:]}}
            try:
                atomic_write_text(self.path, json.dumps(doc, ensure_ascii=False), mkdir=True)
            except (OSError, TypeError, ValueError) as exc:
                if not self._said_no:
                    self._said_no = True
                    print(f"gguf headers: not kept on disk ({exc}); the next start reads them again", flush=True)
                return False
            self._dirty = False
            return True


_MEMORY = None
_MEMORY_LOCK = threading.Lock()


def header_memory():
    """The process's one memory of headers."""
    global _MEMORY
    with _MEMORY_LOCK:
        if _MEMORY is None:
            from caravan.admin.paths import GGUF_HEADERS_FILE
            _MEMORY = HeaderMemory(GGUF_HEADERS_FILE)
        return _MEMORY
