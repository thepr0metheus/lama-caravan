//! A router's graph: its nodes, their settings, its schedule rules and its edges.

use super::*;

impl RouterDsl {
    pub(super) fn valid_edge_ref(reference: &str, node_ids: &BTreeSet<String>, out_ids: &BTreeSet<String>) -> bool {
        if let Some(input) = reference.strip_prefix("in:") {
            return !input.is_empty();
        }
        if let Some(rule) = reference.strip_prefix("rule:") {
            return node_ids.contains(rule);
        }
        if let Some(output) = reference.strip_prefix("out:") {
            return ["srv:", "cb:", "eng:", "mm:"].iter().any(|kind| output.starts_with(kind)) || out_ids.contains(output);
        }
        false
    }

    pub(super) fn one_of(edge: Option<&Value>, edge_ids: &BTreeSet<String>) -> String {
        let said = Coerce::text(edge);
        if edge_ids.contains(&said) { said } else { String::new() }
    }

    fn queue_config(config: &Value, edge_ids: &BTreeSet<String>) -> Value {
        let edge = |key: &str| Self::one_of(config.get(key), edge_ids);
        let bounded = |key: &str, default: i64, least: i64, most: i64| {
            config.get(key).map_or(Some(default), Coerce::int).map_or(default, |said| said.clamp(least, most))
        };
        let slots = config.get("maxSlots").filter(|said| !said.is_null()).and_then(Coerce::int).map(|said| said.clamp(1, 64));
        json!({"admitEdge": edge("admitEdge"), "spillEdge": edge("spillEdge"), "maxSlots": slots, "abortPct": bounded("abortPct", 85, 1, 100), "keepaliveSec": bounded("keepaliveSec", 20, 5, 120)})
    }

    /// A node's config, by its type.
    pub fn node_config(kind: &str, config: Option<&Value>, edge_ids: &BTreeSet<String>) -> Value {
        let empty = json!({});
        let config = config.filter(|config| config.is_object()).unwrap_or(&empty);
        let edge = |key: &str| Self::one_of(config.get(key), edge_ids);
        let rows = |key: &str| {
            config.get(key).filter(|rows| Coerce::truthy(Some(*rows))).and_then(Value::as_array).map_or(&[][..], Vec::as_slice)
        };
        match kind {
            "byModel" => {
                let cases: Vec<Value> = rows("cases")
                    .iter()
                    .filter(|case| case.is_object())
                    .filter_map(|case| {
                        let target = Coerce::text(case.get("edge"));
                        let matched = Word::cut(case.get("match"), 120);
                        (edge_ids.contains(&target) && !matched.is_empty()).then(|| json!({"match": matched, "edge": target}))
                    })
                    .collect();
                json!({"cases": cases, "elseEdge": edge("elseEdge")})
            }
            "schedule" => Self::schedule_config(config, edge_ids),
            "weighted" => {
                let weights: Vec<Value> = rows("weights")
                    .iter()
                    .filter(|row| row.is_object())
                    .filter_map(|row| {
                        let target = Coerce::text(row.get("edge"));
                        // absent-ok: `int(wt.get("pct") or 0)`, and a weight that does not read counts for nothing.
                        edge_ids
                            .contains(&target)
                            .then(|| json!({"edge": target, "pct": Coerce::whole(row.get("pct")).clamp(0, 100)}))
                    })
                    .collect();
                json!({"weights": weights})
            }
            "failover" => {
                let mut order: Vec<String> = Vec::new();
                for said in rows("order") {
                    let id = Coerce::str_of(Some(said));
                    if edge_ids.contains(&id) && !order.contains(&id) {
                        order.push(id);
                    }
                }
                json!({"order": order})
            }
            "queue" => Self::queue_config(config, edge_ids),
            "onError" => json!({"mainEdge": edge("mainEdge"), "rescueEdge": edge("rescueEdge")}),
            "requestSize" => {
                let said = config.get("maxTokensAt").map_or(Some(300), Coerce::int);
                json!({"maxTokensAt": said.map_or(300, |at| at.clamp(1, 100_000))})
            }
            _ => json!({}),
        }
    }

    pub(super) fn schedule_config(config: &Value, edge_ids: &BTreeSet<String>) -> Value {
        let rows = |key: &str| {
            config.get(key).filter(|rows| Coerce::truthy(Some(*rows))).and_then(Value::as_array).map_or(&[][..], Vec::as_slice)
        };
        if config.get("grid").is_some() || config.get("outputs").is_some() {
            let outputs: Vec<Value> = rows("outputs")
                .iter()
                .filter(|row| row.is_object())
                .filter_map(|row| {
                    let id = Word::of(row.get("id"));
                    let said =
                        if Coerce::truthy(row.get("name")) { Word::cut(row.get("name"), 40) } else { "output".to_string() };
                    (!id.is_empty()).then(|| json!({"id": id, "name": said}))
                })
                .collect();
            let known: BTreeSet<String> = outputs.iter().map(|row| Coerce::text(row.get("id"))).collect();
            let mut grid: Vec<Value> = rows("grid")
                .iter()
                .take(7)
                .map(|row| {
                    let cells = row.as_array().map_or(&[][..], Vec::as_slice);
                    let line: Vec<Value> = (0..24)
                        .map(|hour| {
                            cells
                                .get(hour)
                                .and_then(Value::as_str)
                                .filter(|cell| known.contains(*cell))
                                .map_or(Value::Null, |cell| json!(cell))
                        })
                        .collect();
                    Value::Array(line)
                })
                .collect();
            while grid.len() < 7 {
                grid.push(Value::Array(vec![Value::Null; 24]));
            }
            return json!({"outputs": outputs, "grid": grid});
        }
        let windows: Vec<Value> = rows("windows").iter().filter(|row| row.is_object()).map(|row| json!({"days": Self::days(row.get("days")), "from": Self::hhmm(row.get("from"), "00:00"), "to": Self::hhmm(row.get("to"), "23:59")})).collect();
        json!({"windows": windows, "thenEdge": Self::one_of(config.get("thenEdge"), edge_ids), "elseEdge": Self::one_of(config.get("elseEdge"), edge_ids)})
    }

    pub(super) fn days(raw: Option<&Value>) -> Vec<String> {
        raw.and_then(Value::as_array)
            .into_iter()
            .flatten()
            .map(|day| Coerce::first_letters(&Coerce::strip(&Coerce::str_of(Some(day))).to_lowercase(), 3).to_string())
            .filter(|day| Self::WEEKDAYS.contains(&day.as_str()))
            .collect()
    }

    /// A 'HH:MM' string clamped to a valid 24h time; `fallback` for what is none.
    pub(super) fn hhmm(value: Option<&Value>, fallback: &str) -> String {
        let said = Coerce::text(value);
        let word = Coerce::strip(&said);
        let shape = word.split_once(':').filter(|(hour, minute)| {
            (1..=2).contains(&hour.len())
                && minute.len() == 2
                && hour.chars().chain(minute.chars()).all(|letter| letter.is_ascii_digit())
        });
        let Some((hour, minute)) = shape else {
            return fallback.to_string();
        };
        // absent-ok: both are one or two digits, as the shape above says.
        let (hour, minute): (i64, i64) = (hour.parse().unwrap_or(0), minute.parse().unwrap_or(0));
        format!("{:02}:{:02}", hour.min(23), minute.min(59))
    }

    /// The optional routing graph.
    pub(super) fn graph(raw: Option<&Value>, out_ids: &BTreeSet<String>) -> Value {
        let empty = json!({});
        let raw = raw.filter(|raw| raw.is_object()).unwrap_or(&empty);
        let rows = |key: &str| {
            raw.get(key).filter(|rows| Coerce::truthy(Some(*rows))).and_then(Value::as_array).map_or(&[][..], Vec::as_slice)
        };
        let (mut nodes, mut node_ids) = (Vec::new(), BTreeSet::new());
        for node in rows("nodes").iter().filter(|node| node.is_object()) {
            let (id, kind) = (Word::of(node.get("id")), Word::of(node.get("type")));
            if id.is_empty() || node_ids.contains(&id) || !Self::NODE_TYPES.contains(&kind.as_str()) {
                continue;
            }
            node_ids.insert(id.clone());
            let at = |key: &str| Coerce::int_or_zero(node.get(key));
            // absent-ok: `int(n.get(...) or 0)`, and a place that does not read is the corner.
            let (x, y) = at("x").zip(at("y")).unwrap_or((0, 0));
            let config = node.get("config").filter(|config| config.is_object()).cloned().unwrap_or_else(|| json!({}));
            let mut row = json!({"id": id, "type": kind, "x": x, "y": y, "config": config});
            let owner = Word::of(node.get("modelOutputId"));
            if let (true, false, Value::Object(fields)) = (kind == "queue", owner.is_empty(), &mut row) {
                fields.insert("modelOutputId".to_string(), json!(owner));
            }
            nodes.push(row);
        }
        let edges = Self::edges(rows("edges"), &node_ids, out_ids);
        let edge_ids: BTreeSet<String> = edges.iter().map(|edge| Coerce::text(edge.get("id"))).collect();
        for node in &mut nodes {
            let kind = Coerce::text(node.get("type"));
            let config = Self::node_config(&kind, node.get("config"), &edge_ids);
            if let Value::Object(fields) = node {
                fields.insert("config".to_string(), config);
            }
        }
        let mut inputs = Map::new();
        for (port, config) in
            raw.get("inputs").and_then(Value::as_object).into_iter().flatten().filter(|(_, config)| config.is_object())
        {
            // absent-ok: `int(cfg.get(...) or 0)`: a wait that does not read is none, and none is not kept.
            let wait = Coerce::whole(config.get("clientTimeoutSeconds")).clamp(0, 86400);
            if wait > 0 {
                inputs.insert(port.clone(), json!({"clientTimeoutSeconds": wait}));
            }
        }
        json!({"nodes": nodes, "edges": edges, "inputs": inputs})
    }

    pub(super) fn edges(raw: &[Value], node_ids: &BTreeSet<String>, out_ids: &BTreeSet<String>) -> Vec<Value> {
        let (mut edges, mut ids, mut seen) = (Vec::new(), BTreeSet::new(), BTreeSet::new());
        for edge in raw.iter().filter(|edge| edge.is_object()) {
            let (from, to) = (Word::of(edge.get("from")), Word::of(edge.get("to")));
            if from == to
                || !Self::valid_edge_ref(&from, node_ids, out_ids)
                || !Self::valid_edge_ref(&to, node_ids, out_ids)
                || !seen.insert((from.clone(), to.clone()))
            {
                continue;
            }
            let said = Word::of(edge.get("id"));
            let mut id = if said.is_empty() { format!("e{}", edges.len() + 1) } else { said };
            while ids.contains(&id) {
                id = format!("e{}_{id}", edges.len() + 1);
            }
            ids.insert(id.clone());
            let mut row = json!({"id": id, "from": from, "to": to});
            let port = Word::of(edge.get("schedPortId"));
            if let (false, Value::Object(fields)) = (port.is_empty(), &mut row) {
                fields.insert("schedPortId".to_string(), json!(port));
            }
            edges.push(row);
        }
        edges
    }
}
