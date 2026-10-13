"""The single-volume layout's folders, made before any writer needs them — or a
stop that says why they cannot be (DataTree)."""
import os
import sys
from pathlib import Path


class DataTree:
    """The data folder's subfolders, and whether this process can write them.

    In a container the data folder is mounted from the host, and the host's
    rights decide. On Synology a folder carrying an ACL (`ls -ld` shows `+`)
    let its owner write over ssh, yet not the container running as that same
    uid: a container gets no supplementary groups, and the ACL granted write
    through one. The controller died on its first mkdir with a traceback,
    restarted forever, and the browser saw only 502 (a fresh install,
    2026-10-07). The stop now names the folder, the user and the cure.

    `make` and `probe` are the filesystem calls, parameters so a test drives
    the refusal without needing a folder it cannot write.
    """

    SUBDIRS = ("state", "config", "logs", "secrets", "models", "server-backups")
    PROBE = ".write-probe"

    def __init__(self, root, make=None, probe=None, uid=None, gid=None):
        self.root = Path(root)
        self._make = make or (lambda path: path.mkdir(parents=True, exist_ok=True))
        self._probe = probe or self._write_probe
        self.uid = os.getuid() if uid is None else uid
        self.gid = os.getgid() if gid is None else gid

    def _write_probe(self, folder):
        # A folder that exists already says nothing about writing into it.
        path = folder / f"{self.PROBE}.{os.getpid()}"
        path.write_text("", encoding="utf-8")
        path.unlink()

    def problem(self):
        """Why this process cannot keep its data here, or "" once the tree is made."""
        try:
            for sub in self.SUBDIRS:
                self._make(self.root / sub)
            self._probe(self.root / "state")
        except PermissionError as exc:
            return (f"cannot write the data folder {self.root} ({self._where(exc)}) as uid {self.uid}, "
                    f"gid {self.gid}. The folder mounted there must be writable by that user. On Synology "
                    f"a folder with an ACL (ls -ld shows '+') refuses a container even when the user owns "
                    f"it: run 'chmod 755' on the folder on the host")
        except OSError as exc:
            # A read-only mount, a full disk: the same stop, without a cure that is not this one's.
            return f"cannot make the data folder {self.root} ({self._where(exc)})"
        return ""

    def _where(self, exc):
        return f"{getattr(exc, 'filename', None) or self.root}: {exc.strerror or exc}"

    def prepare(self, who, stream=None):
        """Make the tree, or stop the process saying why it cannot."""
        found = self.problem()
        if not found:
            return
        stream = stream or sys.stderr
        print(f"{who}: will not start: {found}", file=stream)
        stream.flush()
        raise SystemExit(2)
