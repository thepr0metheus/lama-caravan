//! A machine with a scout, as the controller keeps it. A scout's report is the whole of its host record: the scout owns it and may replace it. A client is the operator's record in its own section, which no report touches. A machine that is both is two records under one id.

use rules::Coerce;
use serde_json::{Map, Value, json};
use std::net::IpAddr;

/// The record's rules.
pub struct HostRecord;

impl HostRecord {
    /// The fields a report writes, plus when the machine was first and last heard. `ip` is the one a client may carry too.
    pub const FIELDS: [&'static str; 17] = [
        "hostname",
        "ip",
        "agentUrl",
        "gpus",
        "computeApps",
        "engines",
        "cpu",
        "platform",
        "llamaNode",
        "llamaNodes",
        "llamaBinaryVersion",
        "llamaBinaryMtime",
        "llamaUpdate",
        "scoutVersion",
        "scoutCommit",
        "firstSeen",
        "lastSeen",
    ];
    /// Computed on every read and never stored: a stored "online" is a claim that goes stale the moment it is written.
    const COMPUTED: [&'static str; 2] = ["state", "ageSeconds"];

    /// ("online" | "stale", age in seconds or `None`). Never heard is stale with an unknown age: not zero, which would read as "just now".
    pub fn liveness(record: &Value, now: i64, ttl: i64) -> (&'static str, Option<i64>) {
        // absent-ok: `int(... or 0)`: 0 says never heard, as the next line reads it.
        let last_seen = Coerce::whole(record.get("lastSeen"));
        let age = (last_seen != 0).then_some(now - last_seen);
        (if last_seen != 0 && now - last_seen <= ttl { "online" } else { "stale" }, age)
    }

    /// A machine in three words: who it is, what it is called, whether it answers: what a node of the board and the bar's list of machines both say of it.
    pub fn brief(record: &Value) -> Value {
        let id = Coerce::text(record.get("id"));
        let name =
            if Coerce::truthy(record.get("name")) { record.get("name").cloned().unwrap_or(Value::Null) } else { json!(id) };
        json!({"id": id, "name": name, "online": record.get("state").and_then(Value::as_str) == Some("online")})
    }

    /// Where a machine stands in the board's "Machines" section: by its address as a number, then by name. Not by liveness: a machine that goes silent keeps its place. One with no address, or with one that is no IP, stands after the addressed ones, by name.
    pub fn board_order(record: &Value) -> (u8, u8, u128, String) {
        let said = if Coerce::truthy(record.get("name")) { record.get("name") } else { record.get("id") };
        let name = Coerce::text(said);
        let address = Coerce::stripped(record.get("ip")).parse::<IpAddr>();
        match address {
            Ok(IpAddr::V4(ip)) => (0, 4, u128::from(u32::from(ip)), name),
            Ok(IpAddr::V6(ip)) => (0, 6, u128::from(ip), name),
            Err(_) => (1, 0, 0, name),
        }
    }

    /// One old combined record: (host record or none, client record or none). The client keeps its id, name, agents and anything else the operator set, and also `ip`; it is dropped when it came from a report and has no agents.
    pub fn split(row: &Value) -> (Option<Value>, Option<Value>) {
        let Some(fields) = row.as_object() else {
            return (None, None);
        };
        if !Self::FIELDS.iter().any(|key| *key != "ip" && fields.contains_key(*key)) {
            return (None, Some(row.clone()));
        }
        let mut host = Map::new();
        host.insert("id".to_string(), fields.get("id").cloned().unwrap_or(Value::Null));
        let name = if Coerce::truthy(fields.get("name")) { fields.get("name") } else { fields.get("id") };
        host.insert("name".to_string(), name.cloned().unwrap_or(Value::Null));
        for key in Self::FIELDS {
            if let Some(value) = fields.get(key) {
                host.insert(key.to_string(), value.clone());
            }
        }
        let client: Map<String, Value> = fields
            .iter()
            .filter(|(key, _)| (!Self::FIELDS.contains(&key.as_str()) || *key == "ip") && !Self::COMPUTED.contains(&key.as_str()))
            .map(|(key, value)| (key.clone(), value.clone()))
            .collect();
        let has_agents = Coerce::truthy(client.get("agents"));
        (Some(Value::Object(host)), has_agents.then_some(Value::Object(client)))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_machine_never_heard_is_stale_with_no_age() {
        assert_eq!(HostRecord::liveness(&json!({}), 100, 180), ("stale", None));
        assert_eq!(HostRecord::liveness(&json!({"lastSeen": 50}), 100, 180), ("online", Some(50)));
        assert_eq!(HostRecord::liveness(&json!({"lastSeen": 50}), 300, 180), ("stale", Some(250)));
    }

    #[test]
    fn machines_stand_by_their_address_as_a_number() {
        let at = |ip: &str, name: &str| HostRecord::board_order(&json!({"ip": ip, "name": name}));
        assert!(at("10.0.30.9", "b") < at("10.0.30.20", "a"));
        assert!(at("10.0.30.20", "z") < at("nonsense", "a"));
        assert!(at("", "a") < at("", "b"));
    }

    #[test]
    fn a_combined_record_comes_apart() {
        let (host, client) = HostRecord::split(
            &json!({"id": "h", "name": "n", "ip": "10.0.0.1", "gpus": [], "agents": [{"id": "a"}], "state": "stale"}),
        );
        assert_eq!(host, Some(json!({"id": "h", "name": "n", "ip": "10.0.0.1", "gpus": []})));
        assert_eq!(client, Some(json!({"id": "h", "name": "n", "ip": "10.0.0.1", "agents": [{"id": "a"}]})));
        let (host, client) = HostRecord::split(&json!({"id": "h", "gpus": []}));
        assert_eq!(host, Some(json!({"id": "h", "name": "h", "gpus": []})));
        assert_eq!(client, None);
        assert_eq!(HostRecord::split(&json!({"id": "c", "ip": "1"})), (None, Some(json!({"id": "c", "ip": "1"}))));
        assert_eq!(HostRecord::split(&json!(5)), (None, None));
    }
}
