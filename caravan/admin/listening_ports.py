"""Which local TCP ports are listening, and whose, from the kernel's own table
(ListeningPorts)."""
from pathlib import Path


class ListeningPorts:
    """The ports something listens on here, read once from /proc.

    It used to be `ss -ltnp`, run once for every port asked about: a scan of
    the cell range ran it a thousand times, and the container image has no
    `ss` at all — there the command failed, the loop found nothing, and every
    port read as free. The kernel keeps the same table in /proc/net/tcp and
    /proc/net/tcp6: one read answers every port, and a container on the
    host's network reads the host's table.

    Whose a socket is, is found the way ss finds it: its inode among the open
    files of the processes this user may look into. A socket of anyone else
    comes back busy with an unknown owner, (0, "?") — the same answer ss gives
    without root. Where there is no such table (not Linux) `known` is False,
    and a caller that reports to the operator must not take that for "free".
    """

    LISTEN = "0A"

    def __init__(self, proc="/proc"):
        self._proc = Path(proc)
        self._inodes, self.known = self._read()
        self._owners = None

    def _read(self):
        inodes, known = {}, False
        for table in ("tcp", "tcp6"):
            try:
                rows = (self._proc / "net" / table).read_text().splitlines()[1:]
            except OSError:
                continue
            known = True
            for row in rows:
                fields = row.split()
                if len(fields) < 10 or fields[3] != self.LISTEN:
                    continue
                port = int(fields[1].rsplit(":", 1)[1], 16)
                inodes.setdefault(port, set()).add(fields[9])
        return inodes, known

    def _owner_map(self):
        """{socket inode: (pid, command)} over the processes this user may look into."""
        owners = {}
        try:
            entries = list(self._proc.iterdir())
        except OSError:
            return owners
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                comm = (entry / "comm").read_text().strip()
                fds = list((entry / "fd").iterdir())
            except OSError:
                continue
            for fd in fds:
                try:
                    target = fd.readlink().as_posix()
                except OSError:
                    continue
                if target.startswith("socket:[") and target.endswith("]"):
                    owners.setdefault(target[8:-1], (int(entry.name), comm))
        return owners

    def busy(self, port):
        return int(port) in self._inodes

    def owner(self, port):
        """(pid, command) of whoever listens; (0, "?") when busy but not ours to see; (0, "") when free."""
        inodes = self._inodes.get(int(port))
        if not inodes:
            return (0, "")
        if self._owners is None:
            self._owners = self._owner_map()
        for inode in sorted(inodes):
            if inode in self._owners:
                return self._owners[inode]
        return (0, "?")

    def ports(self):
        return sorted(self._inodes)
