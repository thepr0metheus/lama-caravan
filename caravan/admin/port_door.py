"""The controller's firewall door for a port the proxy listens on."""
from caravan.admin.paths import IS_CONTAINER
from caravan.common.procs import run as _run


class ProxyPortDoor:
    """Opens and closes a proxy port in the controller's ufw.

    A bridge, an app port and an agent port serve consumers elsewhere on the
    LAN, so a route's port opens when the route appears and closes when it
    goes (save_agent_proxy_config compares the ports before and after). The
    opening lived as three copies of the same six lines in three mints, and
    nothing ever closed a port: every number the fleet had handed out stayed
    open after its route was gone. Best effort and silent without the sudo rule, as it always
    was — the route works either way, the door is a convenience — and inert in
    the container, which has no ufw.
    """

    def __init__(self, run=_run, in_container=IS_CONTAINER):
        self._run = run
        self._in_container = in_container

    def open(self, port):
        self._ufw(["allow"], port)

    def close(self, port):
        self._ufw(["delete", "allow"], port)

    def _ufw(self, verb, port):
        if self._in_container:
            return
        try:
            self._run(["sudo", "-n", "ufw", *verb, str(int(port))], timeout=5)
        except Exception:
            pass


PORT_DOOR = ProxyPortDoor()
