//! Each wired local model owns its queue. Edges that went to a queue node go to the model; the node is the model's, and its main edge goes on to the model.

use super::dsl::RouterDsl;
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};

/// A graph being reconciled.
pub struct ModelQueues {
    nodes: Vec<Value>,
    edges: Vec<Value>,
    inputs: Value,
    local_ids: BTreeSet<String>,
    cloud_refs: BTreeSet<String>,
    router_id: String,
}

impl ModelQueues {
    /// The queues of `graph` over these outputs.
    pub fn new(graph: Value, outputs: &[Value], router_id: &str) -> Self {
        let is_cloud = |row: &&Value| row.get("upstreamType").and_then(Value::as_str) == Some("cloud");
        Self {
            nodes: Coerce::list(graph.get("nodes")),
            edges: Coerce::list(graph.get("edges")),
            inputs: graph.get("inputs").cloned().unwrap_or_else(|| json!({})),
            local_ids: outputs.iter().filter(|row| !is_cloud(row)).map(|row| Coerce::text(row.get("id"))).collect(),
            cloud_refs: outputs.iter().filter(is_cloud).map(|row| format!("out:{}", Coerce::text(row.get("id")))).collect(),
            router_id: router_id.to_string(),
        }
    }

    fn word(row: &Value, key: &str) -> String {
        Coerce::text(row.get(key))
    }

    /// The node's main edge, by its index: the edge it admits to, else the first that is not its spill.
    fn main_edge(&self, node: &Value) -> Option<usize> {
        let from = format!("rule:{}", Self::word(node, "id"));
        let config = node.get("config");
        let said = |key: &str| config.and_then(|config| config.get(key)).and_then(Value::as_str).map(str::to_string);
        let outgoing: Vec<usize> =
            self.edges.iter().enumerate().filter(|(_, edge)| Self::word(edge, "from") == from).map(|(at, _)| at).collect();
        let edge_id = |at: &usize| self.edges.get(*at).map(|edge| Self::word(edge, "id"));
        let admit = said("admitEdge");
        let spill = said("spillEdge");
        outgoing
            .iter()
            .find(|at| edge_id(at) == admit && admit.is_some())
            .or_else(|| outgoing.iter().find(|at| edge_id(at) != spill))
            .copied()
    }

    fn available_id(prefix: &str, used: &BTreeSet<String>) -> String {
        let (mut candidate, mut suffix) = (prefix.to_string(), 1);
        while used.contains(&candidate) {
            candidate = format!("{prefix}:{suffix}");
            suffix += 1;
        }
        candidate
    }

    fn adopt(&mut self) -> Result<BTreeMap<String, usize>, AppError> {
        let mut owners = BTreeMap::new();
        for at in 0..self.nodes.len() {
            let Some(node) = self.nodes.get(at).filter(|node| node.get("type").and_then(Value::as_str) == Some("queue")).cloned()
            else {
                continue;
            };
            let mut output = Self::word(&node, "modelOutputId");
            if output.is_empty() {
                let target = self
                    .main_edge(&node)
                    .and_then(|main| self.edges.get(main))
                    .map_or_else(String::new, |edge| Self::word(edge, "to"));
                if let Some(said) = target.strip_prefix("out:").filter(|said| self.local_ids.contains(*said)) {
                    output = said.to_string();
                }
            }
            if output.is_empty() {
                continue;
            }
            if owners.contains_key(&output) {
                return Err(AppError::with_status(
                    format!("Local model {output} has multiple queue policies; resolve them before saving"),
                    409,
                ));
            }
            if let Some(Value::Object(fields)) = self.nodes.get_mut(at) {
                fields.insert("modelOutputId".to_string(), json!(output));
                fields.insert("modelQueueActive".to_string(), json!(false));
            }
            owners.insert(output.clone(), at);
            let reference = format!("rule:{}", Self::word(&node, "id"));
            self.retarget(&reference, &format!("out:{output}"));
        }
        Ok(owners)
    }

    fn retarget(&mut self, old: &str, new: &str) {
        for edge in self.edges.iter_mut().filter(|edge| edge.get("to").and_then(Value::as_str) == Some(old)) {
            if let Value::Object(fields) = edge {
                fields.insert("to".to_string(), json!(new));
            }
        }
    }

    /// A cloud main has no admission queue.
    fn remove_cloud_passthroughs(&mut self) {
        let mut removed = BTreeSet::new();
        for node in self.nodes.clone() {
            let plain = node.get("type").and_then(Value::as_str) == Some("queue")
                && Self::word(&node, "modelOutputId").is_empty()
                && !Coerce::truthy(node.get("config").and_then(|config| config.get("spillEdge")));
            if !plain {
                continue;
            }
            let target = self.main_edge(&node).and_then(|main| self.edges.get(main)).map(|edge| Self::word(edge, "to"));
            if let Some(target) = target.filter(|target| self.cloud_refs.contains(target)) {
                let id = Self::word(&node, "id");
                self.retarget(&format!("rule:{id}"), &target);
                removed.insert(id);
            }
        }
        self.nodes.retain(|node| !removed.contains(&Self::word(node, "id")));
        let froms: BTreeSet<String> = removed.iter().map(|id| format!("rule:{id}")).collect();
        self.edges.retain(|edge| !froms.contains(&Self::word(edge, "from")));
    }

    fn ensure_main(&mut self, node_at: usize, output: &str) {
        let Some(node) = self.nodes.get(node_at).cloned() else {
            return;
        };
        let main = match self.main_edge(&node) {
            Some(main) => main,
            None => {
                let used: BTreeSet<String> = self.edges.iter().map(|edge| Self::word(edge, "id")).collect();
                let id = Self::available_id(&format!("model-main:{output}"), &used);
                self.edges
                    .push(json!({"id": id, "from": format!("rule:{}", Self::word(&node, "id")), "to": format!("out:{output}")}));
                self.edges.len() - 1
            }
        };
        let mut main_id = String::new();
        if let Some(Value::Object(fields)) = self.edges.get_mut(main) {
            fields.insert("to".to_string(), json!(format!("out:{output}")));
            main_id = fields.get("id").map_or_else(String::new, |id| Coerce::text(Some(id)));
        }
        if let Some(config) = self.nodes.get_mut(node_at).and_then(|node| node.get_mut("config")).and_then(Value::as_object_mut) {
            config.insert("admitEdge".to_string(), json!(main_id));
        }
    }

    /// The graph as it is kept.
    pub fn reconcile(mut self) -> Result<Value, AppError> {
        self.remove_cloud_passthroughs();
        let owners = self.adopt()?;
        for output in self.local_ids.clone() {
            let target = format!("out:{output}");
            let owner = owners.get(&output).copied();
            let main = owner.and_then(|at| self.nodes.get(at).cloned()).and_then(|node| self.main_edge(&node));
            let connected = self.edges.iter().enumerate().any(|(at, edge)| Self::word(edge, "to") == target && Some(at) != main);
            if owner.is_none() && !connected {
                continue;
            }
            let at = owner.unwrap_or_else(|| {
                let used: BTreeSet<String> = self.nodes.iter().map(|node| Self::word(node, "id")).collect();
                let id = Self::available_id(&format!("model-queue:{}:{output}", self.router_id), &used);
                self.nodes.push(json!({"id": id, "type": "queue", "x": 0, "y": 0, "config": {}, "modelOutputId": output}));
                self.nodes.len() - 1
            });
            self.ensure_main(at, &output);
            let edge_ids: BTreeSet<String> = self.edges.iter().map(|edge| Self::word(edge, "id")).collect();
            if let Some(Value::Object(fields)) = self.nodes.get_mut(at) {
                fields.insert("modelQueueActive".to_string(), json!(connected));
                let config = RouterDsl::node_config("queue", fields.get("config"), &edge_ids);
                fields.insert("config".to_string(), config);
            }
        }
        self.merge_doubles();
        Ok(json!({"nodes": self.nodes, "edges": self.edges, "inputs": self.inputs}))
    }

    /// Two edges of one (from, to, port) are one: the roles nodes hold by edge id follow the one that stays.
    fn merge_doubles(&mut self) {
        let mut pairs: BTreeMap<(String, String, String), String> = BTreeMap::new();
        let mut remap: BTreeMap<String, String> = BTreeMap::new();
        let mut kept = Vec::with_capacity(self.edges.len());
        for edge in self.edges.drain(..) {
            let pair = (Self::word(&edge, "from"), Self::word(&edge, "to"), Self::word(&edge, "schedPortId"));
            match pairs.get(&pair) {
                Some(first) => {
                    remap.insert(Self::word(&edge, "id"), first.clone());
                }
                None => {
                    pairs.insert(pair, Self::word(&edge, "id"));
                    kept.push(edge);
                }
            }
        }
        self.edges = kept;
        for node in &mut self.nodes {
            let Some(config) = node.get_mut("config").and_then(Value::as_object_mut) else {
                continue;
            };
            Self::follow(config, &remap);
        }
    }

    fn follow(config: &mut Map<String, Value>, remap: &BTreeMap<String, String>) {
        for key in ["admitEdge", "spillEdge", "mainEdge", "rescueEdge"] {
            if let Some(to) = config.get(key).and_then(Value::as_str).and_then(|said| remap.get(said)).cloned() {
                config.insert(key.to_string(), json!(to));
            }
        }
        let renamed = |edge: &str| remap.get(edge).map_or_else(|| edge.to_string(), Clone::clone);
        if let Some(weights) = config.get("weights").and_then(Value::as_array).filter(|weights| !weights.is_empty()).cloned() {
            let mut merged: Vec<(String, i64)> = Vec::new();
            for weight in &weights {
                let edge = renamed(&Coerce::text(weight.get("edge")));
                // absent-ok: a weight was made with its share.
                let share = Coerce::i64_or_zero(weight.get("pct"));
                match merged.iter_mut().find(|row| row.0 == edge) {
                    Some(row) => row.1 += share,
                    None => merged.push((edge, share)),
                }
            }
            config.insert(
                "weights".to_string(),
                Value::Array(merged.into_iter().map(|(edge, pct)| json!({"edge": edge, "pct": pct})).collect()),
            );
        }
        if let Some(order) = config.get("order").and_then(Value::as_array).filter(|order| !order.is_empty()).cloned() {
            let mut out: Vec<String> = Vec::new();
            for edge in &order {
                let edge = renamed(&Coerce::str_of(Some(edge)));
                if !out.contains(&edge) {
                    out.push(edge);
                }
            }
            config.insert("order".to_string(), json!(out));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn outputs() -> Vec<Value> {
        vec![json!({"id": "srv:1", "upstreamType": "llama"}), json!({"id": "cb:p", "upstreamType": "cloud"})]
    }

    #[test]
    fn a_wired_model_gets_its_queue() {
        let graph = json!({"nodes": [], "edges": [{"id": "e1", "from": "in:p", "to": "out:srv:1"}], "inputs": {}});
        let done = ModelQueues::new(graph, &outputs(), "r").reconcile().unwrap();
        let nodes = done.get("nodes").unwrap().as_array().unwrap();
        assert_eq!(nodes.len(), 1);
        let node = nodes.first().unwrap();
        assert_eq!(node.get("id"), Some(&json!("model-queue:r:srv:1")));
        assert_eq!(node.get("modelQueueActive"), Some(&json!(true)));
        assert_eq!(node.get("config").unwrap().get("admitEdge"), Some(&json!("model-main:srv:1")));
        assert_eq!(done.get("edges").unwrap().as_array().unwrap().len(), 2);
    }

    #[test]
    fn a_model_nothing_wires_has_none() {
        let done = ModelQueues::new(json!({"nodes": [], "edges": []}), &outputs(), "r").reconcile().unwrap();
        assert_eq!(done.get("nodes"), Some(&json!([])));
    }

    #[test]
    fn a_queue_in_front_of_a_cloud_goes() {
        let graph = json!({"nodes": [{"id": "q", "type": "queue", "config": {}}], "edges": [{"id": "e1", "from": "in:p", "to": "rule:q"}, {"id": "e2", "from": "rule:q", "to": "out:cb:p"}]});
        let done = ModelQueues::new(graph, &outputs(), "r").reconcile().unwrap();
        assert_eq!(done.get("nodes"), Some(&json!([])));
        assert_eq!(done.get("edges"), Some(&json!([{"id": "e1", "from": "in:p", "to": "out:cb:p"}])));
    }

    #[test]
    fn two_queues_of_one_model_are_refused() {
        let graph = json!({"nodes": [{"id": "a", "type": "queue", "config": {}, "modelOutputId": "srv:1"}, {"id": "b", "type": "queue", "config": {}, "modelOutputId": "srv:1"}], "edges": []});
        assert_eq!(ModelQueues::new(graph, &outputs(), "r").reconcile().unwrap_err().status, 409);
    }
}
