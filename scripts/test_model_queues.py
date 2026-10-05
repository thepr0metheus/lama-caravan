#!/usr/bin/env python3
"""Model-owned queue lifecycle, legacy adoption and real proxy graph routing."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caravan.admin.output_refs import RouterOutputRefs
from caravan.admin.router_dsl import normalize_router
from caravan.common.queue_policy import SharedQueuePolicy
from caravan.common.errors import AppError
from caravan.proxy.graph import apply_router, apply_router_spill


class ModelQueuesTest(unittest.TestCase):
    @staticmethod
    def router(edges=None, nodes=None):
        return normalize_router({"id": "router:default", "outputs": [
            {"id": "srv:A", "upstreamType": "llama", "upstreamHost": "host-a", "upstreamPort": 22001},
            {"id": "srv:B", "upstreamType": "llama", "upstreamHost": "host-b", "upstreamPort": 22002},
            {"id": "cb:C", "upstreamType": "cloud", "providerId": "cloud-c"},
        ], "graph": {"nodes": nodes or [], "edges": edges or []}})

    @staticmethod
    def edge(target="srv:A", source="in:skynet:proxy:8101", eid="incoming"):
        return {"id": eid, "from": source, "to": f"out:{target}"}

    @staticmethod
    def queues(router):
        return {n["modelOutputId"]: n for n in router["graph"]["nodes"] if n.get("modelOutputId")}

    @staticmethod
    def config(router):
        return {"routers": [router], "policy": {}}

    @staticmethod
    def route():
        return {"port": 8101, "routerId": "router:default", "label": "agent primary", "clientTimeoutSeconds": 120}

    def test_unwired_and_cloud_have_no_automatic_queue(self):
        self.assertFalse(self.queues(self.router()))
        self.assertFalse(self.queues(self.router([self.edge("cb:C")])))

    def test_first_cable_creates_one_active_queue(self):
        router = self.router([self.edge()])
        queue = self.queues(router)["srv:A"]
        self.assertTrue(queue["modelQueueActive"])
        self.assertNotIn("stickySlotSec", queue["config"])
        self.assertEqual(router["graph"]["edges"][0]["to"], "out:srv:A")
        self.assertEqual(normalize_router(router), router)

    def test_empty_cloud_legacy_queue_becomes_direct_cable(self):
        router = self.router([{"id": "input", "from": "in:skynet:proxy:8101", "to": "rule:q"},
                              self.edge("cb:C", source="rule:q", eid="main")],
                             [{"id": "q", "type": "queue", "config": {"admitEdge": "main"}}])
        self.assertFalse(router["graph"]["nodes"])
        self.assertEqual(router["graph"]["edges"], [{"id": "input", "from": "in:skynet:proxy:8101", "to": "out:cb:C"}])
        self.assertEqual(apply_router(self.route(), self.config(router))["providerId"], "cloud-c")

    def test_several_models_and_several_cables(self):
        router = self.router([self.edge(), self.edge(source="in:other", eid="other"), self.edge("srv:B", eid="b")])
        self.assertEqual(set(self.queues(router)), {"srv:A", "srv:B"})
        self.assertTrue(all(q["modelQueueActive"] for q in self.queues(router).values()))

    def test_rule_cable_activates_queue(self):
        router = self.router([self.edge(source="rule:r")], [{"id": "r", "type": "roundRobin"}])
        self.assertTrue(self.queues(router)["srv:A"]["modelQueueActive"])

    def test_disconnect_hides_and_reconnect_keeps_settings(self):
        router = self.router([self.edge()])
        queue = self.queues(router)["srv:A"]
        queue["config"]["maxSlots"] = 3
        router["graph"]["edges"] = [e for e in router["graph"]["edges"] if e["id"] != "incoming"]
        router = normalize_router(router)
        self.assertFalse(self.queues(router)["srv:A"]["modelQueueActive"])
        router["graph"]["edges"].append(self.edge())
        router = normalize_router(router)
        self.assertTrue(self.queues(router)["srv:A"]["modelQueueActive"])
        self.assertEqual(self.queues(router)["srv:A"]["config"]["maxSlots"], 3)

    def test_rewire_activates_new_model_hides_old(self):
        router = self.router([self.edge()])
        router["graph"]["edges"][0]["to"] = "out:srv:B"
        router = normalize_router(router)
        self.assertFalse(self.queues(router)["srv:A"]["modelQueueActive"])
        self.assertTrue(self.queues(router)["srv:B"]["modelQueueActive"])

    def test_legacy_adoption_preserves_settings_and_role_ids(self):
        nodes = [{"id": "legacy", "type": "queue", "config": {
            "admitEdge": "main", "spillEdge": "spill", "spillPct": 7, "stickySlotSec": 11,
            "maxSlots": 2, "loadingModelWaitSec": 123}}]
        edges = [{"id": "input", "from": "in:skynet:proxy:8101", "to": "rule:legacy"},
                 self.edge(source="rule:legacy", eid="main"), self.edge("cb:C", source="rule:legacy", eid="spill")]
        router = self.router(edges, nodes)
        queue = self.queues(router)["srv:A"]
        self.assertEqual(queue["id"], "legacy")
        self.assertEqual(queue["config"]["spillEdge"], "spill")
        self.assertFalse(set(SharedQueuePolicy.FIELDS) & set(queue["config"]))
        self.assertEqual(router["graph"]["edges"][0]["to"], "out:srv:A")
        resolved = apply_router(self.route(), self.config(router))
        self.assertEqual(resolved["queuePlan"]["spec"]["maxSlots"], 2)
        self.assertEqual(resolved["queuePlan"]["spec"]["spillRef"], "out:cb:C")

    def test_real_proxy_direct_model_uses_queue(self):
        router = self.router([self.edge()])
        resolved = apply_router(self.route(), self.config(router))
        self.assertEqual(resolved["upstreamPort"], 22001)
        self.assertEqual(resolved["queuePlan"]["spec"]["nodeId"], self.queues(router)["srv:A"]["id"])

    def test_spill_uses_destination_models_own_queue(self):
        router = self.router([self.edge()])
        a = self.queues(router)["srv:A"]
        router["graph"]["edges"].append(self.edge("srv:B", source=f"rule:{a['id']}", eid="spill"))
        a["config"]["spillEdge"] = "spill"
        router = normalize_router(router)
        b = self.queues(router)["srv:B"]
        b["config"]["spillPct"] = 41
        cfg = self.config(router)
        cfg["policy"] = {"cloudFallbackPct": 9, "stickySlotSec": 22, "loadingModelWaitSec": 80}
        first = apply_router(self.route(), cfg)
        self.assertEqual(first["queuePlan"]["spec"]["spillRef"], "out:srv:B")
        second = apply_router_spill(first, cfg, "out:srv:B")
        self.assertEqual(second["queuePlan"]["spec"]["nodeId"], b["id"])
        self.assertEqual(second["queuePlan"]["spec"]["spillPct"], 9)
        self.assertEqual(second["queuePlan"]["spec"]["stickySlotSec"], 22)
        self.assertEqual(second["queuePlan"]["spec"]["loadingModelWaitSec"], 80)
        cloud = apply_router_spill(second, cfg, "out:cb:C")
        self.assertNotIn("queuePlan", cloud)

    def test_dormant_policy_does_not_change_unwired_default(self):
        router = self.router([self.edge()])
        router["graph"]["edges"] = [e for e in router["graph"]["edges"] if e["id"] != "incoming"]
        router = normalize_router(router)
        self.assertNotIn("queuePlan", apply_router(self.route(), self.config(router)))

    def test_global_edit_changes_all_queues_without_rewriting_nodes(self):
        router = self.router([self.edge(), self.edge("srv:B", source="in:skynet:proxy:8102", eid="b")])
        cfg = self.config(router)
        routes = [self.route(), {**self.route(), "port": 8102}]
        for value in (5, 17, 0):
            cfg["policy"] = {"cloudFallbackPct": value, "stickySlotSec": value, "loadingModelWaitSec": value}
            for route in routes:
                spec = apply_router(route, cfg)["queuePlan"]["spec"]
                self.assertEqual({k: spec[k] for k in SharedQueuePolicy.FIELDS},
                                 dict.fromkeys(SharedQueuePolicy.FIELDS, value))
        self.assertFalse(any(set(SharedQueuePolicy.FIELDS) & set(n["config"])
                             for n in self.queues(router).values()))

    def test_shared_values_validation_preserves_zero(self):
        self.assertEqual(SharedQueuePolicy({"cloudFallbackPct": 999, "stickySlotSec": -1,
                                           "loadingModelWaitSec": "bad"}).values(),
                         {"spillPct": 100, "stickySlotSec": 0, "loadingModelWaitSec": 60})
        self.assertEqual(set(SharedQueuePolicy({}).policy_values()),
                         {"cloudFallbackPct", "stickySlotSec", "loadingModelWaitSec"})

    def test_partial_policy_save_preserves_other_settings_and_wiring(self):
        from unittest.mock import patch
        from caravan.admin import proxies_config
        original = {"policy": {"maxSlots": 4, "cloudFallbackPct": 30, "stickySlotSec": 25,
                              "loadingModelWaitSec": 90, "preemptEnabled": False},
                    "routers": [self.router([self.edge()])], "routes": [self.route()]}
        with patch.object(proxies_config, "load_agent_proxy_config", return_value=copy.deepcopy(original)), \
                patch.object(proxies_config, "write_agent_proxy_payload") as write:
            saved = proxies_config.set_agent_proxy_policy({"cloudFallbackPct": 5})
        self.assertEqual(saved["policy"]["cloudFallbackPct"], 5)
        self.assertEqual(saved["policy"]["stickySlotSec"], 25)
        self.assertEqual(saved["policy"]["maxSlots"], 4)
        self.assertFalse(saved["policy"]["preemptEnabled"])
        self.assertEqual(saved["routers"], original["routers"])
        self.assertEqual(saved["routes"], original["routes"])
        write.assert_called_once_with(saved)

    def test_same_port_on_other_host_has_separate_queue(self):
        router = self.router([self.edge(), self.edge("srv:B", eid="b")])
        router["outputs"][1]["upstreamPort"] = 22001
        self.assertEqual(len(self.queues(normalize_router(router))), 2)

    def test_queue_ids_do_not_collide_across_routers(self):
        first = self.router([self.edge()])
        second = copy.deepcopy(first)
        second["id"] = "router:other"
        second["graph"]["nodes"] = []
        second["graph"]["edges"] = [self.edge()]
        second = normalize_router(second)
        self.assertNotEqual(self.queues(first)["srv:A"]["id"], self.queues(second)["srv:A"]["id"])

    def test_conflicting_legacy_policies_are_not_silently_merged(self):
        with self.assertRaises(AppError) as error:
            self.router([self.edge(source="rule:q1", eid="a"), self.edge(source="rule:q2", eid="b")],
                        [{"id": "q1", "type": "queue"}, {"id": "q2", "type": "queue"}])
        self.assertEqual(error.exception.status, 409)

    def test_output_move_and_drop_follow_owned_queue(self):
        router = self.router([self.edge()])
        refs = RouterOutputRefs(router)
        self.assertEqual(len(refs.edges_touching("srv:A")), 1)
        refs.rewrite(lambda value: "srv:new" if value == "srv:A" else value)
        self.assertIn("srv:new", self.queues(router))
        refs.drop("srv:new")
        self.assertFalse(self.queues(router))
        self.assertFalse(router["graph"]["edges"])

    def test_missing_output_keeps_settings_until_it_returns(self):
        router = self.router([self.edge()])
        original = copy.deepcopy(router["outputs"])
        router["outputs"] = router["outputs"][1:]
        router = normalize_router(router)
        self.assertFalse(self.queues(router)["srv:A"]["modelQueueActive"])
        router["outputs"] = original
        self.assertTrue(self.queues(normalize_router(router))["srv:A"]["modelQueueActive"])

    def test_adoption_merges_converging_weighted_edges_without_losing_weight(self):
        nodes = [{"id": "q", "type": "queue", "config": {"admitEdge": "main"}},
                 {"id": "w", "type": "weighted", "config": {"weights": [
                     {"edge": "via", "pct": 30}, {"edge": "direct", "pct": 20}, {"edge": "cloud", "pct": 50}]}}]
        edges = [{"id": "via", "from": "rule:w", "to": "rule:q"},
                 self.edge(source="rule:w", eid="direct"), self.edge("cb:C", source="rule:w", eid="cloud"),
                 self.edge(source="rule:q", eid="main")]
        router = self.router(edges, nodes)
        weighted = next(n for n in router["graph"]["nodes"] if n["id"] == "w")
        self.assertEqual(weighted["config"]["weights"], [{"edge": "via", "pct": 50}, {"edge": "cloud", "pct": 50}])
        self.assertEqual(normalize_router(router), router)


if __name__ == "__main__":
    unittest.main()
