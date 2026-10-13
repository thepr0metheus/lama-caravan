"""A pool's own ports are gone (the owner, 2026-10-12: "now everyone comes in
through one address with their own key").

A client of the caravan calls one address — the entry — with its own key, and
the cable from it on the kanban leads it to its pool (caravan/admin/consumers.py).
A pool's own port was a second way in: a port of its own, open to anyone without
a key, straight into one pool. Its "+ port" button went with the main board's
pools column in 1.3.486, and nothing on the board showed such a port any more,
though it kept answering.

Such a port was a route of kind "service". The proxy serves none now
(caravan/proxy/config.py), the controller takes none in (caravan/admin/router_dsl.py),
and a file that still has one loses it at the controller's start — with a line
in the log naming each port, so a program that called one is not left to guess.
"""
from caravan.admin.proxies_config import read_agent_proxy_payload, write_agent_proxy_payload


class PoolPortsRetired:
    """Takes the pools' own ports out of agent-proxies.json, at the controller's start."""

    KIND = "service"

    def __init__(self, read=None, save=None):
        self.read = read or read_agent_proxy_payload
        self.save = save or write_agent_proxy_payload

    @classmethod
    def is_pool_port(cls, route):
        return isinstance(route, dict) and str(route.get("kind") or "").strip().lower() == cls.KIND

    def migrate(self):
        """Every pool's own port leaves the file. Answers `[{"port", "label", "pool"}]`
        of the ports closed, or None when the file had none."""
        payload = self.read()
        routes = payload.get("routes") if isinstance(payload, dict) else None
        if not isinstance(routes, list):
            return None
        gone = [r for r in routes if self.is_pool_port(r)]
        if not gone:
            return None
        payload["routes"] = [r for r in routes if not self.is_pool_port(r)]
        self.save(payload)
        return [{"port": self._port(r), "label": str(r.get("label") or ""), "pool": str(r.get("providerId") or "")}
                for r in gone]

    @staticmethod
    def _port(route):
        try:
            return int(route.get("port") or 0)
        except (TypeError, ValueError):
            return 0
