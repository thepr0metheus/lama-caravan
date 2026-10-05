"""Own the queue of each wired local model. No I/O or browser-side migration.

The graph keeps the queue's destinations and capacity when its last cable is removed. Main is
an internal edge: callers still connect to the model, and the proxy applies
its queue at that output. Old local queue nodes retain their ids and overflow paths. Operator timings
belong to the global policy.
"""

from caravan.common.errors import AppError


class ModelQueues:
    def __init__(self, graph, outputs, normalize_config, router_id):
        self.graph = graph
        self.local_ids = {o["id"] for o in outputs if o.get("upstreamType") != "cloud"}
        self.cloud_refs = {f"out:{o['id']}" for o in outputs if o.get("upstreamType") == "cloud"}
        self.normalize_config = normalize_config
        self.router_id = router_id

    @property
    def nodes(self):
        return self.graph["nodes"]

    @property
    def edges(self):
        return self.graph["edges"]

    def main_edge(self, node):
        cfg = node["config"]
        outgoing = [e for e in self.edges if e["from"] == f"rule:{node['id']}"]
        return next((e for e in outgoing if e["id"] == cfg.get("admitEdge")), None) or next(
            (e for e in outgoing if e["id"] != cfg.get("spillEdge")), None)

    @staticmethod
    def available_id(prefix, used):
        candidate, suffix = prefix, 1
        while candidate in used:
            candidate = f"{prefix}:{suffix}"
            suffix += 1
        return candidate

    def adopt(self):
        owners = {}
        for node in self.nodes:
            if node["type"] != "queue":
                continue
            output_id = node.get("modelOutputId")
            if not output_id:
                main = self.main_edge(node)
                target = str((main or {}).get("to", ""))
                if target.startswith("out:") and target[4:] in self.local_ids:
                    output_id = target[4:]
            if not output_id:
                continue
            if output_id in owners:
                # Merging two different queue policies would silently choose one.
                raise AppError(f"Local model {output_id} has multiple queue policies; resolve them before saving", 409)
            node["modelOutputId"] = output_id
            node["modelQueueActive"] = False
            owners[output_id] = node
            for edge in self.edges:
                if edge["to"] == f"rule:{node['id']}":
                    edge["to"] = f"out:{output_id}"
        return owners

    def remove_cloud_passthroughs(self):
        """A cloud main has no admission queue. Remove empty legacy wrappers only;
        a configured side path stays explicit instead of losing its settings."""
        removed = set()
        for node in self.nodes:
            if node["type"] != "queue" or node.get("modelOutputId") or node["config"].get("spillEdge"):
                continue
            main = self.main_edge(node)
            if main and main["to"] in self.cloud_refs:
                for edge in self.edges:
                    if edge["to"] == f"rule:{node['id']}":
                        edge["to"] = main["to"]
                removed.add(node["id"])
        self.graph["nodes"] = [n for n in self.nodes if n["id"] not in removed]
        self.graph["edges"] = [e for e in self.edges if e["from"] not in {f"rule:{nid}" for nid in removed}]

    def ensure_main(self, node, output_id):
        main = self.main_edge(node)
        if main is None:
            edge_id = self.available_id(f"model-main:{output_id}", {e["id"] for e in self.edges})
            main = {"id": edge_id, "from": f"rule:{node['id']}", "to": f"out:{output_id}"}
            self.edges.append(main)
        main["to"] = f"out:{output_id}"
        node["config"]["admitEdge"] = main["id"]

    def reconcile(self):
        self.remove_cloud_passthroughs()
        owners = self.adopt()
        for output_id in sorted(self.local_ids):
            node = owners.get(output_id)
            main = self.main_edge(node) if node else None
            connected = any(e["to"] == f"out:{output_id}" and e is not main for e in self.edges)
            if node is None and not connected:
                continue
            if node is None:
                node_id = self.available_id(f"model-queue:{self.router_id}:{output_id}", {n["id"] for n in self.nodes})
                node = {"id": node_id, "type": "queue", "x": 0, "y": 0, "config": {},
                        "modelOutputId": output_id}
                self.nodes.append(node)
            self.ensure_main(node, output_id)
            node["modelQueueActive"] = connected
            node["config"] = self.normalize_config("queue", node["config"], {e["id"] for e in self.edges})
        # Adoption may make two old paths identical. Keep role pointers stable by
        # remapping them to the surviving edge, rather than dropping a branch.
        pairs, remap, edges = {}, {}, []
        for edge in self.edges:
            pair = (edge["from"], edge["to"], edge.get("schedPortId"))
            if pair in pairs:
                remap[edge["id"]] = pairs[pair]
            else:
                pairs[pair] = edge["id"]
                edges.append(edge)
        self.graph["edges"] = edges
        for node in self.nodes:
            for key in ("admitEdge", "spillEdge", "mainEdge", "rescueEdge"):
                value = node["config"].get(key)
                if value in remap:
                    node["config"][key] = remap[value]
            weights = node["config"].get("weights")
            if weights:
                merged = {}
                for weight in weights:
                    edge_id = remap.get(weight["edge"], weight["edge"])
                    merged[edge_id] = merged.get(edge_id, 0) + weight["pct"]
                node["config"]["weights"] = [{"edge": edge_id, "pct": pct} for edge_id, pct in merged.items()]
            order = node["config"].get("order")
            if order:
                node["config"]["order"] = list(dict.fromkeys(remap.get(edge_id, edge_id) for edge_id in order))
        return self.graph
