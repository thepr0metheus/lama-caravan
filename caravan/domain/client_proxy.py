"""An agent's assignment and its routes — a class, not a three-key dict.

Three places build this record's shape: the normalizer in `admin/topology.py`,
the rebuild in `admin/proxy_ops.py`, and provisioning in
`admin/fleet_clients.py`. The count of three isn't the problem by itself — the
problem is that the normalizer REBUILDS the record from scratch, so a field it
doesn't name quietly disappears on the next save. This already happened: the
`manual` flag had to be named separately, and right next to it sits a comment
saying "leave this agent alone", silently reverted to automatic — the worst
failure this flag can have.

So "don't forget to name the field" must not be something that can be
forgotten. The field list lives here, in one place, and all three go through
it: an added field survives a save at every writer at once, or at none of
them.

The class holds SHAPE and refusal rules, not policy: who is allowed to write,
and what wins in a merge, are the caller's questions.
"""
from caravan.common.errors import AppError

#: What a proxy port is called inside the caravan. The namespace is checked
#: by its own guard (scripts/check_proxy_id_namespace.py) — only assembly here.
PROXY_ID_PREFIX = "skynet:proxy:"


class ProxyRoute:
    """One role of one agent: which proxy port it uses.

    `role` defaults to "primary" — that's how the rebuild used to behave, and
    the snapshot pins it. `proxy_id` can be empty: a client's live report
    knows its own endpoint but not the internal id, and an empty string here
    is more honest than a missing key.
    """

    __slots__ = ("role", "proxy_id", "endpoint", "context_length", "context_auto",
                 "model_name", "model_name_auto")

    def __init__(self, role="primary", proxy_id="", endpoint="",
                 context_length=None, context_auto=None, model_name=None,
                 model_name_auto=None):
        self.role = str(role or "primary").strip()
        self.proxy_id = str(proxy_id or "").strip()
        self.endpoint = str(endpoint or "").strip()
        #: Context window the operator set FOR THIS consumer. Wins over the
        #: model's own number: each client has its own budget, and the model
        #: knows nothing about it. None means unset; zero and garbage also
        #: give None, because a client would read zero as a real limit.
        self.context_length = self._positive_int(context_length)
        #: "Take whatever the model reports." Stored only when turned on: a
        #: made-up False on a route nobody ever touched would read as an
        #: operator decision.
        self.context_auto = None if context_auto is None else bool(context_auto)
        #: The name this port advertises its model under. A client looks up
        #: ITS OWN id in `/v1/models` and, not finding it, falls back to its
        #: built-in default — so a window honestly published under the wrong
        #: name never reaches it. Empty means whatever the upstream calls
        #: itself is published as-is.
        self.model_name = (str(model_name).strip()[:120] or None) if model_name else None
        #: "Open the lock": advertise the model under its own name and leave
        #: the name above unused. Stored only when turned on — a made-up
        #: False on a route nobody ever touched would read as an operator
        #: decision (the same rule as the window's checkbox).
        self.model_name_auto = None if model_name_auto is None else bool(model_name_auto)

    @staticmethod
    def _positive_int(value):
        try:
            value = int(value) if value not in (None, "", False) else None
        except (TypeError, ValueError):
            return None
        return value if value and value > 0 else None

    @classmethod
    def for_port(cls, role, port, server_ip):
        """A route to an issued port. The one place that assembles the
        `proxyId`/`endpoint` pair: it used to be written by two callers, and
        the port has to be the same one in both halves — the snapshot pins
        that."""
        port = int(port)
        return cls(role=role, proxy_id=f"{PROXY_ID_PREFIX}{port}",
                   endpoint=f"http://{server_ip}:{port}/v1")

    @classmethod
    def from_raw(cls, raw):
        if not isinstance(raw, dict):
            raise AppError("route must be an object", 400)
        route = cls(role=raw.get("role"), proxy_id=raw.get("proxyId"), endpoint=raw.get("endpoint"),
                    context_length=raw.get("contextLength"), context_auto=raw.get("contextAuto"),
                    model_name=raw.get("modelName"), model_name_auto=raw.get("modelNameAuto"))
        if not route.endpoint:
            raise AppError("route.endpoint is required", 400)
        return route

    @property
    def port(self):
        """The port out of the id, if it's there. 0 means "unknown", not
        "port zero"."""
        tail = self.proxy_id.rsplit(":", 1)[-1] if self.proxy_id else ""
        return int(tail) if tail.isdigit() else 0

    def to_dict(self):
        # Settings that were never set aren't written at all: a route the
        # operator never touched keeps exactly the old three-key shape it
        # always had — so the transition needs no record migration.
        out = {"role": self.role, "proxyId": self.proxy_id, "endpoint": self.endpoint}
        if self.context_length is not None:
            out["contextLength"] = self.context_length
        if self.context_auto is not None:
            out["contextAuto"] = self.context_auto
        if self.model_name:
            out["modelName"] = self.model_name
        if self.model_name_auto is not None:
            out["modelNameAuto"] = self.model_name_auto
        return out


class AgentAssignment:
    """Where one agent goes — and what the operator decided about it by hand.

    `manual` means "provisioning stays out of this". The flag is stored only
    when it's set: a made-up False on a record nobody ever touched would read
    as an operator decision.
    """

    __slots__ = ("agent_id", "routes", "manual")

    def __init__(self, agent_id, routes=None, manual=None):
        self.agent_id = str(agent_id or "").strip()
        if not self.agent_id:
            raise AppError("assignment.agentId is required", 400)
        self.routes = list(routes or [])
        self.manual = None if manual is None else bool(manual)

    @classmethod
    def from_raw(cls, raw):
        if not isinstance(raw, dict):
            raise AppError("assignment must be an object", 400)
        raw_routes = raw.get("routes") or []
        if not isinstance(raw_routes, list):
            raise AppError("assignment.routes must be a list", 400)
        routes, seen = [], set()
        for item in raw_routes:
            route = ProxyRoute.from_raw(item)
            if route.role in seen:
                raise AppError(f"duplicate route role: {route.role}", 400)
            seen.add(route.role)
            routes.append(route)
        return cls(agent_id=raw.get("agentId"), routes=routes, manual=raw.get("manual"))

    @classmethod
    def rewired(cls, agent_id, previous_raw, route):
        """A record rebuilt from a client's LIVE report.

        The report knows one thing: which port the agent uses right now. It
        doesn't know what the operator decided about this route — and has no
        right to erase that. The proxy reconcile used to build the record
        from the report alone, so the context window and the "manual" flag
        disappeared for EVERY online agent, even when the port hadn't
        changed; the preview meanwhile showed a rewire "from port X to port
        X" and said nothing about the settings it was dropping.

        Liveness comes from `route`; settings come from the previous record
        of the same role. The record keeps a single route: fallback pairs
        have been retired, and a rebuild must not resurrect them.
        """
        prev = previous_raw if isinstance(previous_raw, dict) else {}
        prev_routes = prev.get("routes")
        same_role = next((r for r in (prev_routes if isinstance(prev_routes, list) else [])
                          if isinstance(r, dict)
                          and str(r.get("role") or "primary").strip() == route.role), None)
        if same_role is not None:
            if route.context_length is None:
                route.context_length = ProxyRoute._positive_int(same_role.get("contextLength"))
            if route.context_auto is None and same_role.get("contextAuto") is not None:
                route.context_auto = bool(same_role.get("contextAuto"))
            if route.model_name is None and same_role.get("modelName"):
                route.model_name = str(same_role.get("modelName")).strip()[:120] or None
            if route.model_name_auto is None and same_role.get("modelNameAuto") is not None:
                route.model_name_auto = bool(same_role.get("modelNameAuto"))
        return cls(agent_id, [route], manual=prev.get("manual"))

    def route(self, role):
        return next((r for r in self.routes if r.role == role), None)

    def set_route(self, route):
        """Sets the route for its role: replaces an existing one, else adds it.

        Replacement, not a skip — this is the 2026-07-20 fix: provisioning
        issued a new port when the old one vanished, and added it "if the
        role doesn't exist yet", which in that case was never true. The
        record kept standing on the dead port, the gate fired again, and a
        new port got minted on every board poll.
        """
        existing = self.route(route.role)
        if existing is None:
            self.routes.append(route)
        else:
            # What moves is LIVENESS — where the agent is reached. Settings
            # the operator set on this role are not cancelled by a port move:
            # the same split as the board's merge.
            existing.role, existing.proxy_id, existing.endpoint = route.role, route.proxy_id, route.endpoint
            if route.context_length is not None:
                existing.context_length = route.context_length
            if route.context_auto is not None:
                existing.context_auto = route.context_auto
            if route.model_name is not None:
                existing.model_name = route.model_name
            if route.model_name_auto is not None:
                existing.model_name_auto = route.model_name_auto
        return route

    def to_dict(self):
        out = {"agentId": self.agent_id, "routes": [r.to_dict() for r in self.routes]}
        if self.manual is not None:
            out["manual"] = self.manual
        return out
