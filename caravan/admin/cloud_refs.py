"""Everything that points at a cloud model — a model block, `cb:<id>`."""
from caravan.admin.proxies_config import load_agent_proxy_config


class CloudModelRefs:
    """What points at a cloud model, read from one snapshot of agent-proxies.json.

    A model the provider stopped offering may leave by itself only when nothing
    points at it, and the delete confirm lists what would break. The first
    version of this list (cloud_block_refs) saw bridges, cables, the queue's
    roles and some rules, and missed a 🛟 backup's main and backup cables' roles,
    the default a router keeps in reserve (dormantDefault), an agent's own
    cloud route and its ↑☁ fallback — a confirm that said "nothing references
    this block" about a model three agents fell back to.

    One snapshot answers for many models: the automatic clean-up asks about
    every model that left a provider at once.
    """

    def __init__(self, cfg):
        self._routes = [r for r in (cfg.get("routes") or []) if isinstance(r, dict)]
        self._routers = [r for r in (cfg.get("routers") or []) if isinstance(r, dict)]

    @classmethod
    def load(cls):
        return cls(load_agent_proxy_config())

    @staticmethod
    def _port(route):
        return {"port": route.get("port"), "label": route.get("label") or ""}

    def of(self, block_id):
        block_id = str(block_id or "").strip()
        out_ref = f"cb:{block_id}"
        edge_ref = f"out:{out_ref}"
        bridges, routes, fallbacks = [], [], []
        for r in self._routes:
            if str(r.get("providerId") or "") == block_id:
                (bridges if r.get("kind") == "service" else routes).append(self._port(r))
            if str(r.get("cloudFallbackProviderId") or "") == block_id:
                fallbacks.append(self._port(r))
        edges, queue_roles, rescue_roles, rule_hits = [], [], [], []
        for router in self._routers:
            rid = router.get("id")
            graph = router.get("graph") or {}
            hit_edges = [e for e in (graph.get("edges") or []) if isinstance(e, dict)
                         and edge_ref in (str(e.get("to") or ""), str(e.get("from") or ""))]
            hit_ids = {str(e.get("id")) for e in hit_edges}
            edges.extend({"router": rid, "id": e.get("id"), "from": e.get("from"), "to": e.get("to")}
                         for e in hit_edges)
            for n in (graph.get("nodes") or []):
                node_cfg = (n or {}).get("config") or {}
                if n.get("type") == "queue":
                    roles, into = (("admitEdge", "admit"), ("spillEdge", "spill")), queue_roles
                elif n.get("type") == "onError":
                    roles, into = (("mainEdge", "main"), ("rescueEdge", "backup")), rescue_roles
                else:
                    continue
                for key, role in roles:
                    if str(node_cfg.get(key) or "") in hit_ids:
                        into.append({"router": rid, "node": n.get("id"), "role": role})
            rules = router.get("rules") or {}
            for kind in ("default", "dormantDefault", "audioOutput", "embeddingsOutput"):
                if str(rules.get(kind) or "") == out_ref:
                    rule_hits.append({"router": rid, "rule": kind})
            for kind in ("schedule", "bySource"):
                if any(str((r or {}).get("output") or "") == out_ref for r in (rules.get(kind) or [])):
                    rule_hits.append({"router": rid, "rule": kind})
            if out_ref in (rules.get("failover") or []):
                rule_hits.append({"router": rid, "rule": "failover"})
        return {"bridges": bridges, "routes": routes, "fallbacks": fallbacks, "edges": edges,
                "queueRoles": queue_roles, "rescueRoles": rescue_roles, "rules": rule_hits}

    def in_use(self, block_id):
        return any(self.of(block_id).values())
