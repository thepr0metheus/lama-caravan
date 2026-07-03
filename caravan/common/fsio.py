"""Filesystem helpers."""
import os
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
