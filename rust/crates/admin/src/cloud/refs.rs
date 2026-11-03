//! Everything that points at a pool: `cb:<id>` in Routing, an agent route's `providerId`.

use crate::proxies::output_refs::RouterOutputRefs;
use rules::Coerce;
use serde_json::{Value, json};

/// What points at a pool, read from one snapshot of the proxy's settings.
pub struct CloudModelRefs {
    routes: Vec<Value>,
    routers: Vec<Value>,
}

impl CloudModelRefs {
    const HOLDING_RULES: [&'static str; 6] = ["default", "audioOutput", "embeddingsOutput", "schedule", "bySource", "failover"];

    /// The reading of `cfg`.
    pub fn new(cfg: &Value) -> Self {
        let objects = |key: &str| -> Vec<Value> {
            cfg.get(key).and_then(Value::as_array).into_iter().flatten().filter(|row| row.is_object()).cloned().collect()
        };
        Self { routes: objects("routes"), routers: objects("routers") }
    }

    fn port(route: &Value) -> Value {
        json!({"port": route.get("port"), "label": Coerce::text(route.get("label"))})
    }

    /// Every reference to a pool.
    pub fn of(&mut self, block_id: &str) -> Value {
        let block_id = Coerce::strip(block_id);
        let out_ref = format!("cb:{block_id}");
        let (mut routes, mut fallbacks) = (Vec::new(), Vec::new());
        for route in &self.routes {
            if Coerce::text(route.get("providerId")) == block_id {
                routes.push(Self::port(route));
            }
            if Coerce::text(route.get("cloudFallbackProviderId")) == block_id {
                fallbacks.push(Self::port(route));
            }
        }
        let (mut edges, mut queue_roles, mut rescue_roles, mut rule_hits) = (Vec::new(), Vec::new(), Vec::new(), Vec::new());
        for router in &mut self.routers {
            let router_id = router.get("id").cloned().unwrap_or(Value::Null);
            let graph = router.get("graph").cloned().unwrap_or(Value::Null);
            let refs = RouterOutputRefs::new(router);
            let hit_edges = refs.edges_touching(&out_ref);
            let hit_ids: Vec<String> = hit_edges.iter().map(|edge| Coerce::str_of(edge.get("id"))).collect();
            for edge in &hit_edges {
                edges.push(json!({"router": router_id, "id": edge.get("id"), "from": edge.get("from"), "to": edge.get("to")}));
            }
            for node in graph.get("nodes").and_then(Value::as_array).into_iter().flatten() {
                let config = node.get("config").cloned().unwrap_or(Value::Null);
                let kind = node.get("type").and_then(Value::as_str);
                let (roles, into) = match kind {
                    Some("queue") => ([("admitEdge", "admit"), ("spillEdge", "spill")], &mut queue_roles),
                    Some("onError") => ([("mainEdge", "main"), ("rescueEdge", "backup")], &mut rescue_roles),
                    _ => continue,
                };
                for (key, role) in roles {
                    if hit_ids.contains(&Coerce::text(config.get(key))) {
                        into.push(json!({"router": router_id, "node": node.get("id"), "role": role}));
                    }
                }
            }
            for rule in refs.rules_naming(&out_ref) {
                rule_hits.push(json!({"router": router_id, "rule": rule}));
            }
        }
        json!({"routes": routes, "fallbacks": fallbacks, "edges": edges, "queueRoles": queue_roles, "rescueRoles": rescue_roles, "rules": rule_hits})
    }

    /// Whether anything points at it.
    pub fn in_use(&mut self, block_id: &str) -> bool {
        let found = self.of(block_id);
        found.as_object().is_some_and(|fields| fields.values().any(|rows| Coerce::truthy(Some(rows))))
    }

    /// What would stop reaching the pool if it went: the operator is asked about these.
    pub fn held(&mut self, pool_id: &str) -> Value {
        let out = format!("cb:{pool_id}");
        let (mut cables, mut rules) = (0, Vec::<&str>::new());
        for router in &mut self.routers {
            let refs = RouterOutputRefs::new(router);
            cables += refs.edges_touching(&out).len();
            for rule in refs.rules_naming(&out) {
                if Self::HOLDING_RULES.contains(&rule) && !rules.contains(&rule) {
                    rules.push(rule);
                }
            }
        }
        json!({"cables": cables, "rules": rules})
    }

    /// Everything the routers of `cfg` point at the pool disconnected; how much.
    pub fn cut(cfg: &mut Value, pool_id: &str) -> i64 {
        let out = format!("cb:{pool_id}");
        let routers = cfg.get_mut("routers").and_then(Value::as_array_mut).into_iter().flatten();
        routers.filter(|router| router.is_object()).map(|router| RouterOutputRefs::new(router).drop(&out)).sum()
    }

    /// Moves what points at one pool onto another, in `cfg`: "move the cables" when a pool is deleted. Each router gets the new pool's output
    /// when it lacks one.
    pub fn move_onto(cfg: &mut Value, from_id: &str, to_id: &str, output: Option<&Value>) -> i64 {
        let (old, new) = (format!("cb:{from_id}"), format!("cb:{to_id}"));
        let mut moved = 0;
        for router in cfg.get_mut("routers").and_then(Value::as_array_mut).into_iter().flatten() {
            if let Some(output) = output {
                let has = router
                    .get("outputs")
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten()
                    .any(|row| row.get("id").and_then(Value::as_str) == Some(new.as_str()));
                if !has {
                    let mut rows = Coerce::list(router.get("outputs"));
                    rows.push(output.clone());
                    Coerce::put(router, "outputs", Value::Array(rows));
                }
            }
            moved += RouterOutputRefs::new(router).rewrite(&|said| if said == old { new.clone() } else { said.to_string() });
        }
        for route in cfg.get_mut("routes").and_then(Value::as_array_mut).into_iter().flatten() {
            if route.is_object() && Coerce::text(route.get("cloudFallbackProviderId")) == from_id {
                Coerce::put(route, "cloudFallbackProviderId", json!(to_id));
                moved += 1;
            }
        }
        moved
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cfg() -> Value {
        json!({
            "routes": [{"port": 1, "label": "a", "providerId": "p"}, {"port": 2, "cloudFallbackProviderId": "p"}],
            "routers": [{
                "id": "r",
                "outputs": [{"id": "cb:p"}],
                "rules": {"default": "cb:p", "dormantDefault": "cb:p"},
                "graph": {"nodes": [{"id": "q", "type": "queue", "config": {"admitEdge": "e1"}}], "edges": [{"id": "e1", "from": "n", "to": "out:cb:p"}]},
            }],
        })
    }

    #[test]
    fn every_kind_of_reference_is_found() {
        let mut refs = CloudModelRefs::new(&cfg());
        let found = refs.of("p");
        assert_eq!(found["routes"], json!([{"port": 1, "label": "a"}]));
        assert_eq!(found["fallbacks"], json!([{"port": 2, "label": ""}]));
        assert_eq!(found["edges"][0]["id"], "e1");
        assert_eq!(found["queueRoles"], json!([{"router": "r", "node": "q", "role": "admit"}]));
        assert_eq!(found["rules"], json!([{"router": "r", "rule": "default"}, {"router": "r", "rule": "dormantDefault"}]));
        assert!(refs.in_use("p"));
        assert!(!refs.in_use("other"));
    }

    #[test]
    fn a_dormant_default_does_not_hold_a_pool() {
        let mut refs = CloudModelRefs::new(&cfg());
        assert_eq!(refs.held("p"), json!({"cables": 1, "rules": ["default"]}));
    }

    #[test]
    fn cables_move_onto_another_pool() {
        let mut cfg = cfg();
        let moved = CloudModelRefs::move_onto(&mut cfg, "p", "q", Some(&json!({"id": "cb:q"})));
        assert!(moved > 0);
        assert_eq!(cfg["routes"][1]["cloudFallbackProviderId"], "q");
        assert_eq!(cfg["routers"][0]["rules"]["default"], "cb:q");
        assert_eq!(cfg["routers"][0]["outputs"][1]["id"], "cb:q");
    }
}
