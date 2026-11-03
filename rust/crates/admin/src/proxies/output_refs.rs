//! Every place a router names one of its outputs, in one table.

use rules::Coerce;
use serde_json::{Value, json};
use std::collections::BTreeSet;

/// A router, read and rewritten by the ids of its outputs.
pub struct RouterOutputRefs<'router> {
    router: &'router mut Value,
}

impl<'router> RouterOutputRefs<'router> {
    const RULE_KEYS: [&'static str; 4] = ["default", "dormantDefault", "audioOutput", "embeddingsOutput"];
    const RULE_LISTS: [&'static str; 2] = ["schedule", "bySource"];
    const EDGE_PREFIX: &'static str = "out:";

    /// The refs of a router.
    pub fn new(router: &'router mut Value) -> Self {
        Self { router }
    }

    fn model_queues(&self) -> impl Iterator<Item = &Value> {
        let nodes = self.router.get("graph").and_then(|graph| graph.get("nodes")).and_then(Value::as_array).into_iter().flatten();
        nodes
            .filter(|node| node.get("type").and_then(Value::as_str) == Some("queue") && Coerce::truthy(node.get("modelOutputId")))
    }

    /// The kinds of rule that name `output_id`, in the table's order.
    pub fn rules_naming(&self, output_id: &str) -> Vec<&'static str> {
        let rules = self.router.get("rules");
        let at = |key: &str| rules.and_then(|rules| rules.get(key));
        let mut hits: Vec<&'static str> =
            Self::RULE_KEYS.iter().copied().filter(|key| Coerce::text(at(key)) == output_id).collect();
        for key in Self::RULE_LISTS {
            if at(key).and_then(Value::as_array).into_iter().flatten().any(|row| Coerce::text(row.get("output")) == output_id) {
                hits.push(key);
            }
        }
        if at("failover").and_then(Value::as_array).into_iter().flatten().any(|said| said.as_str() == Some(output_id)) {
            hits.push("failover");
        }
        hits
    }

    /// The edges that touch an output, a model's own main edge not counted.
    pub fn edges_touching(&self, output_id: &str) -> Vec<Value> {
        let reference = format!("{}{output_id}", Self::EDGE_PREFIX);
        let internal: BTreeSet<String> =
            self.model_queues().map(|node| Coerce::text(node.get("config").and_then(|config| config.get("admitEdge")))).collect();
        let edges = self.router.get("graph").and_then(|graph| graph.get("edges")).and_then(Value::as_array).into_iter().flatten();
        edges
            .filter(|edge| {
                edge.is_object()
                    && !internal.contains(&Coerce::text(edge.get("id")))
                    && (Coerce::text(edge.get("from")) == reference || Coerce::text(edge.get("to")) == reference)
            })
            .cloned()
            .collect()
    }

    /// Every output id the router names becomes `new_id_of(id)`, in place: an edge keeps its id, so the roles nodes hold by edge id stay. How many it moved.
    pub fn rewrite(&mut self, new_id_of: &dyn Fn(&str) -> String) -> i64 {
        let mut changed = 0;
        let moved = |said: &str| Some(new_id_of(said)).filter(|new| new != said);
        if let Some(rules) = self.router.get_mut("rules").and_then(Value::as_object_mut) {
            for key in Self::RULE_KEYS {
                if let Some(new) = rules.get(key).and_then(Value::as_str).filter(|said| !said.is_empty()).and_then(moved) {
                    rules.insert(key.to_string(), json!(new));
                    changed += 1;
                }
            }
            for key in Self::RULE_LISTS {
                for row in rules.get_mut(key).and_then(Value::as_array_mut).into_iter().flatten() {
                    if let Some(new) = row.get("output").and_then(Value::as_str).filter(|said| !said.is_empty()).and_then(moved)
                        && let Value::Object(fields) = row
                    {
                        fields.insert("output".to_string(), json!(new));
                        changed += 1;
                    }
                }
            }
            if let Some(list) = rules.get("failover").and_then(Value::as_array).cloned() {
                let new: Vec<Value> = list.iter().map(|said| json!(new_id_of(&Coerce::str_of(Some(said))))).collect();
                if new != list {
                    rules.insert("failover".to_string(), Value::Array(new));
                    changed += 1;
                }
            }
        }
        let Some(graph) = self.router.get_mut("graph").and_then(Value::as_object_mut) else {
            return changed;
        };
        for edge in graph.get_mut("edges").and_then(Value::as_array_mut).into_iter().flatten() {
            let Value::Object(fields) = edge else {
                continue;
            };
            for end in ["from", "to"] {
                let Some(old) = fields.get(end).and_then(Value::as_str).and_then(|said| said.strip_prefix(Self::EDGE_PREFIX))
                else {
                    continue;
                };
                if let Some(new) = moved(old) {
                    fields.insert(end.to_string(), json!(format!("{}{new}", Self::EDGE_PREFIX)));
                    changed += 1;
                }
            }
        }
        for node in graph.get_mut("nodes").and_then(Value::as_array_mut).into_iter().flatten() {
            if node.get("type").and_then(Value::as_str) != Some("queue") {
                continue;
            }
            if let Some(new) = node.get("modelOutputId").and_then(Value::as_str).filter(|said| !said.is_empty()).and_then(moved)
                && let Value::Object(fields) = node
            {
                fields.insert("modelOutputId".to_string(), json!(new));
                changed += 1;
            }
        }
        changed
    }

    /// Everything the router points at `output_id` goes; how many.
    pub fn drop(&mut self, output_id: &str) -> i64 {
        let mut dropped = 0;
        if let Some(rules) = self.router.get_mut("rules").and_then(Value::as_object_mut) {
            for key in Self::RULE_KEYS {
                if rules.get(key).and_then(Value::as_str) == Some(output_id) {
                    rules.shift_remove(key);
                    dropped += 1;
                }
            }
            for key in Self::RULE_LISTS {
                if let Some(rows) = rules.get_mut(key).and_then(Value::as_array_mut) {
                    let before = rows.len();
                    rows.retain(|row| !(row.is_object() && row.get("output").and_then(Value::as_str) == Some(output_id)));
                    dropped += (before - rows.len()) as i64;
                }
            }
            if let Some(list) = rules.get_mut("failover").and_then(Value::as_array_mut) {
                let before = list.len();
                list.retain(|said| said.as_str() != Some(output_id));
                if list.len() != before {
                    dropped += 1;
                }
            }
        }
        let owned: BTreeSet<String> = self
            .model_queues()
            .filter(|node| node.get("modelOutputId").and_then(Value::as_str) == Some(output_id))
            .map(|node| Coerce::text(node.get("id")))
            .collect();
        let Some(graph) = self.router.get_mut("graph").and_then(Value::as_object_mut) else {
            return dropped;
        };
        if !owned.is_empty()
            && let Some(nodes) = graph.get_mut("nodes").and_then(Value::as_array_mut)
        {
            nodes.retain(|node| !owned.contains(&Coerce::text(node.get("id"))));
            dropped += owned.len() as i64;
        }
        if let Some(edges) = graph.get_mut("edges").and_then(Value::as_array_mut) {
            let reference = format!("{}{output_id}", Self::EDGE_PREFIX);
            let froms: BTreeSet<String> = owned.iter().map(|id| format!("rule:{id}")).collect();
            let before = edges.len();
            edges.retain(|edge| {
                let (from, to) = (Coerce::text(edge.get("from")), Coerce::text(edge.get("to")));
                !(edge.is_object() && (from == reference || to == reference || froms.contains(&from)))
            });
            dropped += (before - edges.len()) as i64;
        }
        dropped
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn router() -> Value {
        json!({"rules": {"default": "a", "failover": ["a", "b"], "schedule": [{"output": "a"}]}, "graph": {"edges": [{"id": "e", "from": "in:x", "to": "out:a"}, {"id": "m", "from": "rule:q", "to": "out:a"}], "nodes": [{"id": "q", "type": "queue", "modelOutputId": "a", "config": {"admitEdge": "m"}}]}})
    }

    #[test]
    fn a_rewrite_follows_the_id_everywhere() {
        let mut row = router();
        let mut refs = RouterOutputRefs::new(&mut row);
        assert_eq!(refs.rules_naming("a"), ["default", "schedule", "failover"]);
        assert_eq!(refs.edges_touching("a").len(), 1);
        let moved = refs.rewrite(&|said| if said == "a" { "z".to_string() } else { said.to_string() });
        assert_eq!(moved, 6);
        assert_eq!(row.get("rules").unwrap().get("failover"), Some(&json!(["z", "b"])));
        assert_eq!(row.get("graph").unwrap().get("nodes").unwrap().get(0).unwrap().get("modelOutputId"), Some(&json!("z")));
    }

    #[test]
    fn a_drop_takes_the_queue_and_its_edges_along() {
        let mut row = router();
        let dropped = RouterOutputRefs::new(&mut row).drop("a");
        assert_eq!(dropped, 6);
        assert_eq!(row.get("rules").unwrap().get("failover"), Some(&json!(["b"])));
        assert_eq!(row.get("graph").unwrap().get("edges"), Some(&json!([])));
        assert_eq!(row.get("graph").unwrap().get("nodes"), Some(&json!([])));
    }
}
