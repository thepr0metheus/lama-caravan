"""Filesystem helpers."""
import os
import tempfile
import threading


def read_text(path):
    return path.read_text(encoding="utf-8")


def atomic_write_text(path, text, *, encoding="utf-8", chmod=None, mkdir=False):
    """Write via a per-process/thread temp file + os.replace so readers never see
    a partial file and concurrent writers never clobber each other's temp."""
    if mkdir:
        path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    tmp.write_text(text, encoding=encoding)
    if chmod is not None:
        try:
            os.chmod(tmp, chmod)
        except Exception:
            pass
    tmp.replace(path)


def create_private_text(path, text, *, encoding="utf-8"):
    """Write `text` to a NEW file only its owner can read: whole or not at all,
    and never over a file that is there — FileExistsError when the name is taken.

    atomic_write_text swaps the new file in over the old one, which is right for
    a state file and wrong for a copy that has to outlive the next one: two
    writers of one name leave the second's, and the first is gone. Here the
    finished temp file is hard-linked to its name, so the name appears with all
    its content at once, or the link fails because the name is taken; then the
    temp file is dropped. mkstemp makes the temp file 0600 from its first byte
    and it is synced before the link, so what is under the name is complete and
    was never readable by anyone else.

    Where links are not allowed (some network mounts) the name is taken by an
    exclusive create and written in place — still never over another file, only
    not whole-or-nothing.
    """
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        _write_synced(fd, text, encoding)
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise
        except OSError:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                _write_synced(fd, text, encoding)
            except BaseException:
                os.unlink(path)
                raise
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def _write_synced(fd, text, encoding):
    """Write `text` through the open descriptor, close it, and have it on disk first."""
    with os.fdopen(fd, "w", encoding=encoding) as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())

