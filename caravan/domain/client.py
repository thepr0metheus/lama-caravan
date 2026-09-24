"""A fleet client: the record that it EXISTS, separate from whether it answers.

A client used to appear only from the scout's heartbeat, so "exists" and
"answers" were the same fact. Now an operator can create one by hand, and the
two facts split apart: the record exists and is configured, and a report may
never arrive. This class holds exactly the first half — the record's shape
and the rule for its id. Liveness (`state`, `ageSeconds`) is still computed
from `lastSeen` the same way it always was, so a manual record honestly reads
as "silent", not "running".

The id rule used to live inside heartbeat parsing as a single fifteen-line
comment. Once a client could be created two different ways, it had to move to
one place: otherwise the second path lets through what the first one rejects
— and the consequence is spelled out in the rule itself.
"""
import re

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

        The `manual` mark is not decoration: the scout's report replaces the
        agent list WHOLESALE, and without it a hand-added agent would vanish
        the moment its client ever reported in. The mark is the only thing
        the merge uses to tell "the operator created this" from "this is no
        longer seen".
        """
        agent_id = str(agent_id or "").strip()[:80]
        if not agent_id:
            raise AppError("agentId is required", 400)
        agents = row.setdefault("agents", [])
        if any(str(a.get("id") or "") == agent_id for a in agents if isinstance(a, dict)):
            raise AppError(f'agent "{agent_id}" already exists on this client', 409)
        agent = {"id": agent_id, "name": str(name or agent_id).strip()[:120],
                 "scope": "agent", "manual": True}
        agents.append(agent)
        return agent

    @classmethod
    def merge_manual_agents(cls, reported, previous):
        """The agent list after a report: what the scout said, plus manual ones.

        Liveness still belongs to the scout — an agent it stays silent about
        drops off, same as always. Except the ones the operator created:
        their existence is neither confirmed nor denied by the report.
        """
        seen = {str(a.get("id") or "") for a in reported if isinstance(a, dict)}
        kept = [a for a in (previous or [])
                if isinstance(a, dict) and a.get("manual")
                and str(a.get("id") or "") not in seen]
        return list(reported) + kept

    @classmethod
    def keep_record_agents(cls, reported, previous):
        """The agent list of a hand-made client after a report: the record's own.

        A hand-made client's agents are the operator's records, like its cells
        (decided 2026-09-24 — the scouts are on their way out). A report may
        refresh what it knows about an agent the record has — what it is, where
        and whether it runs — but it neither adds an agent nor takes one away.
        Before, silence removed: a scout whose fleet registry did not answer
        fell back to its one static agent, and nine agents that still held
        proxy ports vanished from the board.

        Whether an agent runs (`runtimeDetected`) is only ever this report's
        word: an agent the report does not mention loses the old answer rather
        than keep a days-old "running". Its name may be refreshed too — the
        operator's own name for an agent lives apart, in agentAliases, and wins
        on the board.
        """
        by_id = {str(a.get("id") or ""): a for a in (reported or []) if isinstance(a, dict)}
        kept = []
        for agent in previous or []:
            if not isinstance(agent, dict):
                continue
            row = {k: v for k, v in agent.items() if k != "runtimeDetected"}
            seen = by_id.get(str(agent.get("id") or ""))
            if seen:
                row.update({k: v for k, v in seen.items() if k not in ("id", "manual")})
            kept.append(row)
        return kept

    @classmethod
    def agent_from_port(cls, agent_id, label=""):
        """An agent a hand-made client's record lost while a proxy port still
        carries its route. Its name is the port's label without the role word
        ("Vega primary" → "Vega"), or its id when the label says
        nothing; what it is and whether it runs are not known, so not claimed.
        """
        name = re.sub(r"\s+(primary|fallback)$", "", str(label or "").strip(), flags=re.I).strip()
        return {"id": str(agent_id), "name": (name or str(agent_id))[:120],
                "kind": "manual", "status": "configured", "manual": True}

    @classmethod
    def adopt(cls, row):
        """Mark an EXISTING record manual. True if anything changed.

        Adoption happens in place, not "create new and delete old": the
        registry is live, its routes carry traffic, and in the gap between
        create and delete they would exist twice or not at all. What changes
        is who owns the record — and with it its agents, marked the operator's
        too: since 2026-09-24 a hand-made client's agents are permanent
        records, and a report can no longer remove them (keep_record_agents).
        Liveness and names are none of adoption's business. Which is also why
        a repeat call is harmless.
        """
        if not isinstance(row, dict) or row.get("manual"):
            return False
        # The controller's sentinel is not a scout client: there is nothing to
        # adopt, and marking it would pretend the operator decided something
        # about it.
        if any(str(row.get("id") or "").casefold() == r.casefold() for r in cls.RESERVED_IDS):
            return False
        row["manual"] = True
        for agent in row.get("agents") or []:
            if isinstance(agent, dict):
                agent["manual"] = True
        return True

    @classmethod
    def manual(cls, host_id, name="", ip="", agent_url=""):
        """A record for a client created by hand.

        `lastSeen` is NOT set: it means "answered at this moment", and a made-up
        value would make a silent client look alive — exactly what this work
        is meant to keep apart. An empty `agents` is a fact too, not a
        placeholder: agents get added to it separately.
        """
        row = {
            "id": cls.validate_id(host_id),
            "name": str(name or host_id).strip()[:120],
            "agents": [],
            "manual": True,
        }
        for key, value in (("ip", ip), ("agentUrl", agent_url)):
            value = str(value or "").strip()[:240]
            if value:
                row[key] = value
        return row
