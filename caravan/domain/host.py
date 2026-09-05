"""Where a cell lives, and what that implies.

Two kinds of host, and the difference is not cosmetic — it decides real
behaviour. A cell on the CONTROLLER is a systemd unit on this machine: it has
generated launch files here (start.sh, cell.json), starting it is a local
action, and its saved command is read from that file. A cell on a CLIENT has
none of that: the controller builds its command and hands it to the scout over
HTTP, and there is nothing on this disk to read.

Written out as `if is_controller_host(...)` at each site, that asymmetry has to
be remembered every time. It was written three times in the slot writers alone,
and the one place that forgot it — a modal that read the command from the
artifact — told the operator that every client cell and every running cell had
"not saved yet" about a command it was serving traffic with.

`is_controller_host` stays where it is: asking "which kind is this" is a fine
question, and it is already a single choke point. What lives here is the ANSWER
to "and therefore what?".
"""
from caravan.admin.paths import CONTROLLER_HOST_ID, canonical_host_id, is_controller_host


class Host:
    """A machine cells run on."""

    #: True when the cell's launch files are generated on THIS disk.
    writes_launch_files = False

    def __init__(self, host_id):
        self.id = canonical_host_id(host_id)

    def __repr__(self):
        return f"<{type(self).__name__} {self.id}>"

    def __eq__(self, other):
        return isinstance(other, Host) and self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def slot_key(self, port):
        """The key a cell on this host is stored under."""
        return f"{self.id}:{int(port)}"

    def refresh_launch_files(self, slot, port, config):
        """Regenerate this cell's launch files and record them on the slot.

        A no-op on a client, and that is the whole point of calling it rather
        than branching: the caller says "this cell moved, refresh it" and does
        not have to remember which hosts that means something for.
        """
        return None


class ControllerHost(Host):
    """The machine the panel itself runs on. Its cells are local systemd units."""

    writes_launch_files = True

    def __init__(self, host_id=CONTROLLER_HOST_ID):
        super().__init__(host_id)

    def refresh_launch_files(self, slot, port, config):
        # Imported here: launch imports the config builder, which imports enough
        # of the admin package that a module-level import would close a cycle.
        from caravan.admin.launch import write_server_cell_artifacts
        if not isinstance(config, dict) or not config:
            return None
        artifact = write_server_cell_artifacts(self.id, port, config)
        if artifact:
            slot["artifact"] = artifact
        return artifact or None


class ClientHost(Host):
    """A machine running caravan-scout. Its cells are started over HTTP, and the
    command they run is built here and sent — never written to this disk."""


def host_for(host_id):
    """The host with this id. Never None; an unknown id is a client.

    A client, not an error: the controller is the one host this process can
    identify with certainty, and everything else is a machine it talks to. An
    id it has not seen before is a client it has not seen before.
    """
    return ControllerHost(host_id) if is_controller_host(host_id) else ClientHost(host_id)
