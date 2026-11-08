//! The models of a machine as its scout's entry lists them, and the router outputs they become.

use super::server_cells::ServerCells;
use crate::common::model_kinds::ModelFacts;
use net::Sha1;
use rules::{BaseUrl, Coerce};
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;

/// A machine's models as its report says them, cleaned for its record.
pub struct MachineModels;

impl MachineModels {
    const STATES: [&'static str; 4] = ["running", "starting", "failed", "stopped"];
    const MODELS: usize = 200;
    const COPIES: usize = 32;

    /// A count the scout said; `None` for what is no whole number at or above zero.
    pub fn count(raw: Option<&Value>) -> Option<i64> {
        raw.and_then(Value::as_i64).filter(|count| *count >= 0)
    }

    fn state(raw: Option<&Value>) -> &str {
        raw.and_then(Value::as_str).filter(|said| Self::STATES.contains(said)).unwrap_or("unknown")
    }

    /// The list as the record keeps it; `None` for a report that lists nothing, which is not the same as an empty list.
    pub fn clean(raw: Option<&Value>) -> Option<Value> {
        let rows = raw?.as_array()?;
        let mut models = Vec::new();
        for item in rows.iter().take(Self::MODELS).filter(|item| item.is_object()) {
            let name: String = Coerce::stripped(item.get("id")).chars().take(200).collect();
            let name = Coerce::strip(&name).to_string();
            if name.is_empty() {
                continue;
            }
            let said = item.get("caravan").filter(|said| said.is_object());
            let at = |key: &str| said.and_then(|said| said.get(key));
            let copies: Vec<Value> = at("copies")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .take(Self::COPIES)
                .filter_map(|copy| {
                    // A copy is its cell: by its id, or by the port a scout of before named it with. Its port is the one it is leased
                    // while it runs, and none while it stands — said as none, never as 0.
                    let id = ServerCells::node_cell(copy)?;
                    let port = Self::count(copy.get("port")).filter(|port| *port != 0);
                    Some(json!({"id": id, "port": port, "state": Self::state(copy.get("state")), "slots": Self::count(copy.get("slots")), "busy": Self::count(copy.get("busy"))}))
                })
                .collect();
            models.push(json!({"id": name, "state": Self::state(at("state")), "slots": Self::count(at("slots")), "busy": Self::count(at("busy")), "copies": copies}));
        }
        Some(Value::Array(models))
    }
}

/// Each model of a machine's entry as a router output, `mm:<hash>`.
pub struct MachineOutputs;

impl MachineOutputs {
    /// The output's id.
    pub fn output_id(host_id: &str, model: &str) -> String {
        let hex = Sha1::of(format!("{host_id}\n{model}").as_bytes());
        format!("mm:{}", hex.get(..12).unwrap_or(&hex))
    }

    /// `(address, port)` of the machine's entry, its scout's as its report gives it; `None` for a report with no address.
    pub fn entry_address(host: &Value) -> Option<(String, u16)> {
        let url = Coerce::stripped(host.get("agentUrl"));
        let place = BaseUrl::read(&url)?;
        let has_port =
            url.split("://").nth(1).and_then(|rest| rest.split('/').next()).is_some_and(|authority| authority.contains(':'));
        (!place.host.is_empty() && has_port).then(|| (place.host.clone(), place.port))
    }

    /// What each cell of the board says of its model, by the cell's id.
    fn cell_facts(server_obj: &Value) -> BTreeMap<String, Map<String, Value>> {
        let rows = server_obj.get("llamaServers").and_then(Value::as_array).into_iter().flatten();
        let mut found = BTreeMap::new();
        for row in rows.filter(|row| row.is_object()) {
            if let Some(id) = row.get("cellId").and_then(rules::CellId::read) {
                found.insert(id, ModelFacts::cell_facts(row));
            }
        }
        found
    }

    fn facts(model: &Value, cells: &BTreeMap<String, Map<String, Value>>) -> Map<String, Value> {
        let copies = model.get("copies").and_then(Value::as_array).into_iter().flatten();
        let said: Vec<&Map<String, Value>> =
            copies.filter_map(|copy| ServerCells::node_cell(copy).and_then(|id| cells.get(&id))).collect();
        let first = said.iter().find(|facts| Coerce::truthy(facts.get("jobs")));
        let mut out: Map<String, Value> = first.map_or_else(Map::new, |facts| {
            facts.iter().filter(|(key, _)| *key != "contextLength").map(|(key, value)| (key.clone(), value.clone())).collect()
        });
        let windows = said
            .iter()
            .filter_map(|facts| facts.get("contextLength").filter(|said| Coerce::truthy(Some(*said))))
            .filter_map(Value::as_i64);
        if let Some(window) = windows.min() {
            out.insert("contextLength".to_string(), json!(window));
        }
        out
    }

    /// One output per model of each machine whose scout lists them, in the order it lists them.
    pub fn outputs(hosts: &[Value], server_obj: &Value) -> Vec<Value> {
        let cells = Self::cell_facts(server_obj);
        let mut outs = Vec::new();
        for host in hosts.iter().filter(|host| host.is_object()) {
            let host_id = Coerce::text(host.get("id"));
            let address = if host_id.is_empty() { None } else { Self::entry_address(host) };
            let Some((address, port)) = address else {
                continue;
            };
            for model in host.get("entryModels").and_then(Value::as_array).into_iter().flatten() {
                let name = Coerce::text(model.get("id"));
                if name.is_empty() {
                    continue;
                }
                let copies = model.get("copies").and_then(Value::as_array).into_iter().flatten();
                let running: Vec<&Value> = copies
                    .filter(|copy| copy.get("state").and_then(Value::as_str) == Some("running"))
                    .filter_map(|copy| copy.get("port"))
                    .collect();
                let mut row = json!({
                    "id": Self::output_id(&host_id, &name), "label": name, "target": format!("{host_id}:machine:{name}"),
                    "upstreamHost": address, "upstreamPort": port, "upstreamType": "machine", "providerId": "",
                    "upstreamModel": name, "hostId": host_id, "copyPorts": running,
                });
                if model.get("state").and_then(Value::as_str) == Some("stopped") {
                    Coerce::put(&mut row, "stopped", json!(true));
                }
                for (key, value) in Self::facts(model, &cells) {
                    Coerce::put(&mut row, &key, value);
                }
                outs.push(row);
            }
        }
        outs
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_report_says_each_model_and_its_copies() {
        let cleaned = MachineModels::clean(Some(&json!([
            {"id": " m ", "caravan": {"state": "running", "slots": 2, "busy": 1, "copies": [{"port": 5, "state": "odd"}, {"port": 0}, {"state": "running"}, {"id": "c7b", "port": null, "state": "stopped"}]}},
            {"id": ""},
            5,
        ])))
        .unwrap();
        assert_eq!(
            cleaned,
            json!([{"id": "m", "state": "running", "slots": 2, "busy": 1, "copies": [
                {"id": "c5", "port": 5, "state": "unknown", "slots": null, "busy": null},
                {"id": "c7b", "port": null, "state": "stopped", "slots": null, "busy": null},
            ]}]),
            "a copy of a scout of before is the cell of its port; a stopped one of now holds no port and is kept; negative: one naming no cell is not"
        );
        assert_eq!(
            MachineModels::clean(Some(&json!([{"id": "m", "caravan": {"copies": [{"port": 0}]}}]))).unwrap()[0]["copies"],
            json!([])
        );
        assert_eq!(MachineModels::clean(None), None);
    }

    #[test]
    fn an_output_id_is_python_s_hash() {
        assert_eq!(MachineOutputs::output_id("h", "m").len(), 15);
        assert_ne!(MachineOutputs::output_id("h", "m"), MachineOutputs::output_id("h", "n"));
    }

    #[test]
    fn an_entry_needs_its_address_and_port() {
        assert_eq!(MachineOutputs::entry_address(&json!({"agentUrl": "http://a:8092"})), Some(("a".to_string(), 8092)));
        assert_eq!(MachineOutputs::entry_address(&json!({"agentUrl": "http://a"})), None);
        assert_eq!(MachineOutputs::entry_address(&json!({})), None);
    }

    #[test]
    fn a_model_becomes_an_output_with_what_its_copies_say() {
        let hosts = [json!({"id": "h", "agentUrl": "http://a:1", "entryModels": [
            {"id": "m", "state": "stopped", "copies": [{"id": "c1", "port": 7, "state": "running"}, {"id": "c2", "port": null, "state": "stopped"}]},
        ]})];
        let outs = MachineOutputs::outputs(&hosts, &json!({}));
        assert_eq!(outs[0]["copyPorts"], json!([7]));
        assert_eq!(outs[0]["stopped"], true);
        assert_eq!(outs[0]["upstreamPort"], 1);
    }
}
