"""A fleet client: the record that it EXISTS, separate from whether it answers.

A client used to appear only from the scout's heartbeat, so "exists" and
"answers" were the same fact. Now an operator can create one by hand, and the
two facts split apart: the record exists and is configured, and a report may
never arrive. This class holds exactly the first half — the record's shape
and the rule for its id. A client has no liveness of its own (2026-09-24):
its agents' traffic says whether it works, and the machine a scout reports is
a separate host record whose liveness is computed on read.

The id rule used to live inside heartbeat parsing as a single fifteen-line
comment. Once a client could be created two different ways, it had to move to
one place: otherwise the second path lets through what the first one rejects
— and the consequence is spelled out in the rule itself.
"""
from caravan.admin.paths import CONTROLLER_HOST_ID, LEGACY_CONTROLLER_HOST_IDS
from caravan.common.errors import AppError


class FleetClient:
    """One client record. The class is about shape and rules, not storage."""

    #: Names a client can never carry, under any circumstances.
    RESERVED_IDS = (CONTROLLER_HOST_ID,) + tuple(LEGACY_CONTROLLER_HOST_IDS)

    @classmethod
    def validate_id(cls, host_id):
        """The client's id, or a refusal.

        The controller's id is a reserved sentinel, and slots are addressed
        as the string "<hostId>:<port>": a client under that name would write
        straight into the controller's own namespace, and two different cells
        would land under one key. A running cell has already vanished from the
        board that way. The id arrives from someone else's config or from a
        form, and nothing but this check stands between them.

        The comparison is case-insensitive ON PURPOSE: a fleet where two
        spellings of the same name both live is a trap for the reader either
        way, so a near-miss is rejected at the door. The LEGACY names are
        reserved forever: an outdated frontend still sends them meaning the
        controller, and a client under that name would be unaddressable.
        """
        host_id = str(host_id or "").strip()[:120]
        if not host_id:
            raise AppError("host.id is required", 400)
        if any(host_id.casefold() == r.casefold() for r in cls.RESERVED_IDS):
            raise AppError(f'host.id "{host_id}" is reserved for the controller — '
                           f"give this client a different hostId", 400)
        return host_id

    @classmethod
    def add_agent(cls, row, agent_id, name=""):
        """Add an agent to the record by hand. Refuses if one already exists.

        Every agent is made this way now: no report adds or removes one
        (2026-09-24), so the record needs no mark saying who made it.
        """
        agent_id = str(agent_id or "").strip()[:80]
        if not agent_id:
            raise AppError("agentId is required", 400)
        agents = row.setdefault("agents", [])
        if any(str(a.get("id") or "") == agent_id for a in agents if isinstance(a, dict)):
            raise AppError(f'agent "{agent_id}" already exists on this client', 409)
        agent = {"id": agent_id, "name": str(name or agent_id).strip()[:120], "scope": "agent"}
        agents.append(agent)
        return agent

    @classmethod
    def new(cls, host_id, name="", ip=""):
        """A record for a client — every client is created by hand.

        `lastSeen` is NOT set: it means "answered at this moment", and a made-up
        value would make a silent client look alive — exactly what this work
        is meant to keep apart. An empty `agents` is a fact too, not a
        placeholder: agents get added to it separately.
        """
        row = {
            "id": cls.validate_id(host_id),
            "name": str(name or host_id).strip()[:120],
            "agents": [],
        }
        # A scout's address is a fact about a machine; its report brings it
        # (HostRecord). A client carries only where its calls come from.
        ip = str(ip or "").strip()[:240]
        if ip:
            row["ip"] = ip
        return row
