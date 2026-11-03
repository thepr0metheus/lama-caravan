//! A fleet client: the record that it EXISTS, separate from whether it answers. A client has no liveness of its own: its agents' traffic says whether it works, and the machine a scout reports is a separate host record.

use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};

/// The record's rules.
pub struct FleetClient;

impl FleetClient {
    /// Names a client can never carry, under any circumstances.
    const RESERVED_IDS: [&'static str; 2] = ["controller", "skynet"];

    /// The client's id, or a refusal. Slots are addressed as "<hostId>:<port>": a client under the controller's name would write straight into its namespace, and two different cells would land under one key. The comparison ignores case ON PURPOSE: a fleet where two spellings of one name both live is a trap.
    pub fn validate_id(host_id: Option<&Value>) -> Result<String, AppError> {
        let said = if Coerce::truthy(host_id) { Coerce::stripped(host_id) } else { String::new() };
        let id = Coerce::first_letters(&said, 120).to_string();
        if id.is_empty() {
            return Err(AppError::new("host.id is required"));
        }
        if Self::RESERVED_IDS.iter().any(|reserved| id.to_lowercase() == *reserved) {
            return Err(AppError::new(format!(
                "host.id \"{id}\" is reserved for the controller — give this client a different hostId"
            )));
        }
        Ok(id)
    }

    /// Adds an agent to the record by hand. Refuses if one already exists.
    pub fn add_agent(row: &mut Map<String, Value>, agent_id: Option<&Value>, name: Option<&Value>) -> Result<Value, AppError> {
        let said = if Coerce::truthy(agent_id) { Coerce::stripped(agent_id) } else { String::new() };
        let id = Coerce::first_letters(&said, 80).to_string();
        if id.is_empty() {
            return Err(AppError::new("agentId is required"));
        }
        let agents = row.entry("agents".to_string()).or_insert_with(|| json!([]));
        let Value::Array(list) = agents else {
            return Err(AppError::new("the client's agents are no list"));
        };
        if list.iter().any(|agent| agent.is_object() && Coerce::text(agent.get("id")) == id) {
            return Err(AppError::with_status(format!("agent \"{id}\" already exists on this client"), 409));
        }
        let named = if Coerce::truthy(name) { Coerce::stripped(name) } else { id.clone() };
        let agent = json!({"id": id, "name": Coerce::first_letters(&named, 120), "scope": "agent"});
        list.push(agent.clone());
        Ok(agent)
    }

    /// A record for a client: every client is created by hand. `lastSeen` is NOT set: a made-up value would make a silent client look alive.
    pub fn new_record(host_id: Option<&Value>, name: Option<&Value>, ip: Option<&Value>) -> Result<Value, AppError> {
        let id = Self::validate_id(host_id)?;
        let said = if Coerce::truthy(name) { Coerce::stripped(name) } else { Coerce::stripped(host_id) };
        let mut row = json!({"id": id, "name": Coerce::first_letters(&said, 120), "agents": []});
        let address = if Coerce::truthy(ip) { Coerce::stripped(ip) } else { String::new() };
        let address = Coerce::first_letters(&address, 240);
        if let (false, Value::Object(fields)) = (address.is_empty(), &mut row) {
            fields.insert("ip".to_string(), json!(address));
        }
        Ok(row)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_controllers_names_are_reserved_in_any_case() {
        assert!(FleetClient::validate_id(Some(&json!("Controller"))).is_err());
        assert!(FleetClient::validate_id(Some(&json!(" SKYNET "))).is_err());
        assert!(FleetClient::validate_id(Some(&json!(""))).is_err());
        assert_eq!(FleetClient::validate_id(Some(&json!(" pi "))).unwrap(), "pi");
    }

    #[test]
    fn an_agent_is_added_once() {
        let mut row = Map::new();
        FleetClient::add_agent(&mut row, Some(&json!("a")), None).unwrap();
        assert_eq!(row.get("agents"), Some(&json!([{"id": "a", "name": "a", "scope": "agent"}])));
        assert_eq!(FleetClient::add_agent(&mut row, Some(&json!("a")), None).unwrap_err().status, 409);
        assert!(FleetClient::add_agent(&mut row, None, None).is_err());
    }

    #[test]
    fn a_new_record_says_only_what_it_was_told() {
        assert_eq!(
            FleetClient::new_record(Some(&json!("c")), None, None).unwrap(),
            json!({"id": "c", "name": "c", "agents": []})
        );
        assert_eq!(
            FleetClient::new_record(Some(&json!("c")), Some(&json!("N")), Some(&json!("10.0.0.1"))).unwrap(),
            json!({"id": "c", "name": "N", "agents": [], "ip": "10.0.0.1"})
        );
    }
}
