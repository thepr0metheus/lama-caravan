"""The scout of the machine this controller runs on — its hands there (MachineScout)."""
import threading
import time

from caravan.admin.controller_machine import ControllerMachine
from caravan.common.errors import AppError


class MachineScout:
    """The scout on the controller's own machine, which does what the controller once did there.

    Powering the machine, its GPU driver, its cards and their reading, its
    busiest processes, the nvidia-smi and btop snapshots: the controller
    asked its own machine for all of these, and a controller in a container has no
    machine to ask — no nvidia-smi, no apt, no sudo, only its own processes.
    So it asks the machine's scout, natively and in a container alike: one
    way, not two. ControllerMachine names that scout by the machine's name.

    A machine with no scout says so (NO_SCOUT) instead of a reading of the
    container or a sudo error, and a scout that does not answer says that,
    in its own words (caravan/service/scout.py). After a read of a path fails,
    that path is not asked again for FAIL_PAUSE seconds: the monitor reads
    every second, and a dead scout must not slow it to one reading in three.
    Per path, because an older scout lacks some paths and answers the others.
    """

    NO_SCOUT = ("there is no scout on the controller's machine — add one (Model servers → Add scout) "
                "to read and act on this machine from the board")
    FAIL_PAUSE = 10.0

    def __init__(self, topology=None, headers=None, controller=None, clock=time.monotonic):
        self._topology = topology
        self._headers = headers
        self._controller = controller
        self._clock = clock
        self._lock = threading.Lock()
        self._failed = {}             # path -> (when, answer) of its last failed read

    def _topo(self):
        if self._topology is None:
            from caravan.admin.state import topology
            return topology
        return self._topology

    def host_id(self):
        """The id of the scout on this controller's machine, or ""."""
        return (self._controller or ControllerMachine()).host_id(self._topo().hosts())

    def host(self):
        """The host record of this controller's machine — what its scout last
        reported, its cards included; {} when no scout reports from it."""
        host_id = self.host_id()
        return dict(self._topo().hosts().get(host_id) or {}) if host_id else {}

    def scout(self):
        """The machine's scout, ready to be called; AppError 409 when there is none."""
        from caravan.service.scout import Scout
        host_id = self.host_id()
        if not host_id:
            raise AppError(self.NO_SCOUT, 409)
        if self._headers is None:
            from caravan.admin.fleet_clients import _scout_headers
            headers = _scout_headers()
        else:
            headers = self._headers
        return Scout.for_host(host_id, self._topo(), headers=headers)

    def read(self, path, timeout=5):
        """The scout's answer, or {ok: False, error} — never raises."""
        key = path.split("?", 1)[0]
        with self._lock:
            failed = self._failed.get(key)
        if failed and self._clock() - failed[0] < self.FAIL_PAUSE:
            return dict(failed[1])
        try:
            answer = self.scout().read(path, timeout=timeout)
        except AppError as exc:
            answer = {"ok": False, "error": str(exc)}
        unusable = not isinstance(answer, dict) or answer.get("ok") is False and "error" in answer
        with self._lock:
            if unusable:
                self._failed[key] = (self._clock(), answer if isinstance(answer, dict)
                                      else {"ok": False, "error": str(answer)})
            else:
                self._failed.pop(key, None)
        return answer

    def post(self, path, payload=None, timeout=15):
        """Ask the scout to act; AppError with its reason when it cannot."""
        return self.scout().post(path, payload or {}, timeout=timeout)


machine_scout = MachineScout()
