"""The key a cell answers to (2026-09-26, the operator's decision).

Every cell of every machine — the caravan's own and the ones in an engine —
takes requests only from the caravan: the controller's proxy puts the cell's
key where the agent's route key was, and a request from anyone else on the
network is refused. ``/health`` stays open, so the board and the scout still
see a cell's state. 127.0.0.1 could not do this: the controller reaches the
cells of other machines over the network, so a cell's port has to be open to
it, and a door on that port that checks nothing is as open as no door.

One secret on the controller, the master. A cell's key is derived from it and
the cell's port — ports are unique across the fleet — so the proxy needs only
the port it is about to call: no table of keys to keep in step with the cells,
and a key that leaks from one cell opens that cell and no other.

The master is created once, by whichever process asks first (the admin at its
start, normally); the file is created exclusively, so two processes starting
together cannot each keep a master of their own.
"""
import hashlib
import hmac
import os
import secrets
from pathlib import Path


class CellKeys:
    """The fleet's cell keys, from the master in `path`."""

    #: Marks the string as a cell key wherever it turns up — a log, a leak.
    PREFIX = "cck1_"
    #: Where a cell's process finds its key: llama-server and vLLM read their
    #: own variables, the caravan's cell servers (cells/) CARAVAN_CELL_KEY. A
    #: cell gets all three — each program reads its own and ignores the rest,
    #: and a command cell that runs one of them by hand is covered as well.
    #: Never on the command line, where any user of the machine reads it.
    ENV_NAMES = ("LLAMA_API_KEY", "VLLM_API_KEY", "CARAVAN_CELL_KEY")

    def __init__(self, path):
        self.path = Path(path)
        self._master = None
        self._stamp = None

    def master(self, *, create=False):
        """The master's bytes; None when there is none yet and `create` is off.
        Re-read when the file changes, so a new master reaches a running proxy."""
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return self._create() if create else None
        stamp = (stat.st_mtime_ns, stat.st_size)
        if self._master is None or stamp != self._stamp:
            text = self.path.read_text(encoding="utf-8").strip()
            self._master = bytes.fromhex(text) if text else None
            self._stamp = stamp
        return self._master

    def _create(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return self.master()
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(secrets.token_hex(32) + "\n")
        return self.master()

    def for_port(self, port, *, create=False):
        """The key of the cell on `port`; None without a master, or for a port
        that is not one."""
        if isinstance(port, int) and not isinstance(port, bool):
            number = port
        elif isinstance(port, str) and port.strip().isdigit():
            number = int(port.strip())
        else:
            return None
        if not 0 < number < 65536:
            return None
        master = self.master(create=create)
        if not master:
            return None
        digest = hmac.new(master, f"cell:{number}".encode(), hashlib.sha256).hexdigest()
        return self.PREFIX + digest[:40]

    def headers(self, port):
        """The header a request to the cell on `port` carries: {} when there is
        no key to carry."""
        key = self.for_port(port)
        return {"Authorization": f"Bearer {key}"} if key else {}

    def env(self, port, *, create=True):
        """What a cell's process gets in its environment: {} without a key."""
        key = self.for_port(port, create=create)
        return {name: key for name in self.ENV_NAMES} if key else {}
