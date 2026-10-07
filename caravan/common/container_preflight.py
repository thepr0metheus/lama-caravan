"""What a container must be told before it may start (ContainerPreflight)."""
import ipaddress
import os
import sys
import time
from datetime import datetime


class ContainerPreflight:
    """The two settings a container cannot guess, checked before anything starts.

    Natively the controller lives on its machine and inherits what the machine
    knows: its clock's time zone and an address the fleet reaches. A container
    knows neither, and both go wrong without a word. Without a zone the process
    runs in UTC, and every schedule — the cells' windows, the router's hours,
    the planned shutdown, the daily model check — fires hours off. Without an
    address the agents are handed http://127.0.0.1:<port>, which leads nowhere
    from their machines. So in a container (CARAVAN_CONTAINER=1) both must be
    stated, or the process does not start and says why.

    The zone is checked twice: by name (zoneinfo must know it) and by effect,
    the C library's offset against the zone's. An image without zone data takes
    TZ=Asia/Tbilisi for UTC silently, and only the second check sees that. UTC
    itself is fine, written out as TZ=UTC. The clocks and the environment are
    parameters, so a test drives every case.
    """

    CONTAINER_VAR = "CARAVAN_CONTAINER"
    ZONE_VAR = "TZ"
    ADDRESS_VAR = "LLAMA_TOPOLOGY_SERVER_IP"

    def __init__(self, env=None, now=None, local_offset=None, zone_offset=None):
        self._env = os.environ if env is None else env
        self._now = now or time.time
        self._local_offset = local_offset or (lambda at: time.localtime(at).tm_gmtoff)
        self._zone_offset = zone_offset or self._zoneinfo_offset

    @classmethod
    def in_container(cls, env=None):
        """Whether this process runs in the caravan's container — the one place that reads it."""
        env = os.environ if env is None else env
        return str(env.get(cls.CONTAINER_VAR, "")).strip() == "1"

    @staticmethod
    def _zoneinfo_offset(name, at):
        from zoneinfo import ZoneInfo
        return int(datetime.fromtimestamp(at, ZoneInfo(name)).utcoffset().total_seconds())

    @staticmethod
    def _hours(seconds):
        return f"UTC{seconds / 3600:+g}"

    def zone_problem(self):
        name = str(self._env.get(self.ZONE_VAR, "")).strip()
        if not name:
            return ("TZ is not set: the container would run in UTC and every schedule would fire "
                    "hours off. Set TZ to this controller's time zone, e.g. TZ=Europe/Berlin "
                    "(TZ=UTC when UTC is meant)")
        at = self._now()
        try:
            zone = self._zone_offset(name.lstrip(":"), at)
        except Exception:  # noqa: BLE001 — any failure to resolve is the same answer
            return f"TZ={name}: no such time zone in this image's zone data"
        local = self._local_offset(at)
        if local != zone:
            return (f"TZ={name}: the zone is {self._hours(zone)}, but the clock runs at "
                    f"{self._hours(local)} — the image has no zone data for the C library")
        return ""

    def address_problem(self):
        raw = str(self._env.get(self.ADDRESS_VAR, "")).strip()
        if not raw:
            return (f"{self.ADDRESS_VAR} is not set: agents would be handed http://127.0.0.1:<port>, "
                    "which leads nowhere from their machines. Set it to this machine's LAN address")
        if raw.lower() == "localhost":
            return f"{self.ADDRESS_VAR}={raw}: that is this container itself, not an address the fleet reaches"
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            return ""        # a name, e.g. caravan.home.arpa — the fleet resolves it
        if ip.is_loopback or ip.is_unspecified:
            return f"{self.ADDRESS_VAR}={raw}: that is this container itself, not an address the fleet reaches"
        return ""

    def problems(self, address=True):
        """Why this process may not start, or [] — outside a container always []."""
        if not self.in_container(self._env):
            return []
        found = [self.zone_problem(), self.address_problem() if address else ""]
        return [problem for problem in found if problem]

    def enforce(self, who, address=True, stream=None):
        """Stop the process, saying why, when the container lacks what it must be told."""
        found = self.problems(address)
        if not found:
            return
        stream = stream or sys.stderr
        print(f"{who}: will not start in a container without these settings:", file=stream)
        for problem in found:
            print(f"  - {problem}", file=stream)
        stream.flush()
        raise SystemExit(2)
