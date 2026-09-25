"""The machine this controller runs on, among the machines with a scout."""
import socket


class ControllerMachine:
    """Which scout's machine is the one this controller runs on.

    Since step 6.8 the controller runs no cell itself: its own machine's
    cells run through that machine's scout, and the machine is a host like
    any other. It is still the one whose panels the controller can fill
    from its own monitor, and the one to show first. A scout reports its
    machine's hostname; the controller knows its own. Nothing else ties the
    two — the scout was paired at 127.0.0.1, an address every machine has.
    """

    def __init__(self, hostname=None):
        self.hostname = self.short(hostname or socket.gethostname())

    @staticmethod
    def short(name):
        return str(name or "").split(".")[0].strip().lower()

    @staticmethod
    def name(hostname=None):
        """This computer's name as the board shows it: the short hostname,
        its case kept — what a scout on this machine reports as its name."""
        return str(hostname or socket.gethostname()).split(".")[0].strip()

    def is_host(self, host):
        """True when `host` (a host record) is this controller's machine."""
        return bool(self.hostname) and isinstance(host, dict) and self.short(host.get("hostname")) == self.hostname

    def host_id(self, hosts):
        """The id of this controller's machine among `hosts` (records by
        id, or a list of them), or "" when no scout reports from it."""
        rows = hosts.values() if isinstance(hosts, dict) else hosts or []
        return next((str(h.get("id") or "") for h in rows if self.is_host(h)), "")
