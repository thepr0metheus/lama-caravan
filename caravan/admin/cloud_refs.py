"""Everything that points at a cloud model — a model block, `cb:<id>`."""
from caravan.admin.output_refs import RouterOutputRefs
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
            refs = RouterOutputRefs(router)
            hit_edges = refs.edges_touching(out_ref)
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
            rule_hits.extend({"router": rid, "rule": kind} for kind in refs.rules_naming(out_ref))
        return {"bridges": bridges, "routes": routes, "fallbacks": fallbacks, "edges": edges,
                "queueRoles": queue_roles, "rescueRoles": rescue_roles, "rules": rule_hits}

    def in_use(self, block_id):
        return any(self.of(block_id).values())


class CloudModelRewire:
    """Moves what points at one cloud model onto another — the "new model"
    window's "move the cables" (the operator's word, 2026-09-27).

    In place: an edge keeps its id and only its end changes, so a queue's
    main and overflow, a 🛟 backup's main and backup, a schedule's port — all
    held by edge id — stay where they were; the router's rules (the default,
    the one in reserve, schedule, by-source, failover, audio, embeddings)
    and an agent's ↑☁ fallback follow too. A model's own ports for apps are
    pins an app chose, not cables, and stay.

    The new model's output goes into every router first: saving a router
    drops a rule that names an output the router does not have (edges to a
    cloud model survive, rules do not), and the next sync of outputs would add
    it anyway — the caller shows the model on the kanban.
    """

    def __init__(self, cfg):
        self.cfg = cfg

    def move(self, from_id, to_id, output=None):
        """Rewire in the snapshot; returns how many references moved. `output`
        is the new model's router output (proxies_config.cloud_block_output)."""
        old, new = f"cb:{from_id}", f"cb:{to_id}"
        for router in self.cfg.get("routers") or []:
            if output and not any(o.get("id") == new for o in router.get("outputs") or []):
                router["outputs"] = list(router.get("outputs") or []) + [dict(output)]
        moved = sum(RouterOutputRefs(router).rewrite(lambda v: new if v == old else v)
                    for router in self.cfg.get("routers") or [])
        for route in self.cfg.get("routes") or []:
            if isinstance(route, dict) and str(route.get("cloudFallbackProviderId") or "") == str(from_id):
                route["cloudFallbackProviderId"] = str(to_id)
                moved += 1
        return moved

