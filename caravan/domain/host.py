"""A machine with a scout, as the controller keeps it.

There were two kinds of host, and the difference decided real behaviour: a
cell on the CONTROLLER was a systemd unit with launch files on this disk, a
cell on a CLIENT was started over HTTP by its scout. Since step 6.8 the
controller runs no cell itself — its own machine's cells run through that
machine's scout — so every cell is the second kind, and what is left here is
the record of a machine a scout reports.
"""
import ipaddress


class HostRecord:
    """What the controller keeps about a machine with a scout — and only that.

    Until 2026-09-24 one record per machine held both this and a client's
    agents, and a heartbeat replaced it wholesale: the operator's fields had to
    be carried back through every report, and a field nobody carried was lost
    on every beat. Now a scout's report is the whole of its host record — the
    scout owns it and may replace it — and a client is the operator's record
    in its own section, which no report touches. A machine that is both is two
    records under one id.
    """

    #: The fields a report writes, plus when the machine was first and last
    #: heard. `ip` is the one a client may carry too: there it is where the
    #: client's calls come from, here where the machine's cells are reached.
    FIELDS = ("hostname", "ip", "agentUrl", "gpus", "computeApps", "cpu", "platform",
              "llamaNode", "llamaNodes", "llamaBinaryVersion", "llamaBinaryMtime",
              "llamaUpdate", "scoutVersion", "firstSeen", "lastSeen")

    #: Computed on every read and never stored: a stored "online" is a claim
    #: that goes stale the moment it is written.
    COMPUTED = ("state", "ageSeconds")

    @classmethod
    def liveness(cls, record, now, ttl):
        """("online" | "stale", age in seconds or None). Never heard is stale
        with an unknown age — not zero, which would read as "just now"."""
        last_seen = int((record or {}).get("lastSeen") or 0)
        age = now - last_seen if last_seen else None
        return ("online" if last_seen and now - last_seen <= ttl else "stale"), age

    @classmethod
    def board_order(cls, record):
        """Where a machine stands in the board's "Model servers" lane: by its
        address as a number (…30.9 before …30.20), then by name. Not by
        liveness: a machine that goes silent keeps its place, as a cell keeps
        its place on its card by port. A machine with no address, or with one
        that is no IP, stands after the addressed ones, by name.

        It was "online first, then by name", and the operator expected the
        order of the addresses."""
        name = str((record or {}).get("name") or (record or {}).get("id") or "")
        try:
            ip = ipaddress.ip_address(str((record or {}).get("ip") or "").strip())
        except ValueError:
            return (1, 0, 0, name)
        return (0, ip.version, int(ip), name)

    @classmethod
    def split(cls, row):
        """One old combined record → (host record or None, client record or None).

        A record carries a host when any report field is on it. The client
        keeps its id, name, agents and anything else the operator set, and
        also `ip`; it is dropped when it came from a report and has no agents —
        a machine that only lends its GPU, which the old record showed as a
        client because there was nowhere else to show it.
        """
        if not isinstance(row, dict):
            return None, None
        reported = [key for key in cls.FIELDS if key in row and key != "ip"]
        if not reported:
            return None, dict(row)
        host = {"id": row.get("id"), "name": row.get("name") or row.get("id")}
        host.update({key: row[key] for key in cls.FIELDS if key in row})
        client = {key: value for key, value in row.items()
                  if key not in cls.FIELDS or key == "ip"}
        for key in cls.COMPUTED:
            client.pop(key, None)
        if not client.get("agents"):
            return host, None
        return host, client
