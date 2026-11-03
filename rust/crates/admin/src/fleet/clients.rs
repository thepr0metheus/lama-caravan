//! The client records on the board, and what the board names the machines.

use crate::app::App;
use crate::domain::client::FleetClient;
use crate::domain::client_proxy::PROXY_ID_PREFIX;
use crate::store::admin::AdminStore;
use crate::store::topology::Topology;
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};

/// The client records of this controller.
pub struct ClientDesk<'app> {
    app: &'app App,
}

impl<'app> ClientDesk<'app> {
    /// The desk of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn proxy_port(route: &Value) -> Option<i64> {
        Coerce::text(route.get("proxyId")).strip_prefix(PROXY_ID_PREFIX).and_then(|tail| tail.parse().ok())
    }

    /// The port next to primary, for a fallback role; `None` when another assignment holds it, or there is no primary.
    pub fn fallback_port_for(&self, assignment: &Value) -> Option<i64> {
        let routes = assignment.get("routes").and_then(Value::as_array).into_iter().flatten();
        let mut routes = routes.filter(|route| route.is_object());
        let primary = routes.find(|route| {
            let role = Coerce::text(route.get("role"));
            role.is_empty() || role == "primary"
        })?;
        let tail = Coerce::text(primary.get("proxyId"));
        let tail = tail.rsplit(':').next().unwrap_or(&tail);
        if tail.is_empty() || !tail.chars().all(|digit| digit.is_ascii_digit()) {
            return None;
        }
        let candidate: i64 = tail.parse::<i64>().ok()? + 1;
        let assignments = self.app.admin.change(|doc| Topology::of(doc).assignments().clone());
        let word = candidate.to_string();
        for entry in assignments.values() {
            for row in entry.get("assignments").and_then(Value::as_array).into_iter().flatten() {
                for route in row.get("routes").and_then(Value::as_array).into_iter().flatten() {
                    if Coerce::text(route.get("proxyId")).rsplit(':').next() == Some(word.as_str()) {
                        return None;
                    }
                }
            }
        }
        Some(candidate)
    }

    /// A client made by hand.
    pub fn create(&self, body: &Value) -> Result<Value, AppError> {
        let said = body.get("hostId").filter(|said| Coerce::truthy(Some(*said))).or_else(|| body.get("id"));
        let mut row = FleetClient::new_record(said, body.get("name"), body.get("ip"))?;
        let id = Coerce::text(row.get("id"));
        if self.app.admin.change(|doc| Topology::of(doc).clients().contains_key(&id)) {
            return Err(AppError::with_status(format!("client already exists: {id}"), 409));
        }
        let name = {
            let named = Coerce::text(row.get("name"));
            if named.is_empty() { id.clone() } else { named }
        };
        if let Value::Object(fields) = &mut row {
            FleetClient::add_agent(fields, Some(&json!(id)), Some(&json!(name)))?;
        }
        self.app.admin.saving(|doc| {
            Topology::of(doc).clients().insert(id.clone(), row.clone());
        });
        Ok(row)
    }

    /// A client deleted.
    pub fn delete(&self, body: &Value) -> Result<Value, AppError> {
        let id = Coerce::stripped(body.get("clientId"));
        if id.is_empty() {
            return Err(AppError::new("clientId is required"));
        }
        if !self.app.admin.change(|doc| Topology::of(doc).clients().contains_key(&id)) {
            return Err(AppError::with_status(format!("client not found: {id}"), 404));
        }
        self.app.admin.saving(|doc| {
            let mut topology = Topology::of(doc);
            topology.clients().shift_remove(&id);
            topology.assignments().shift_remove(&id);
        });
        Ok(json!({"ok": true, "clientId": id}))
    }

    /// Port → how many assignment entries, on any host and of any agent, route through it.
    fn port_claims(assignments: &Map<String, Value>) -> BTreeMap<i64, i64> {
        let mut claims = BTreeMap::new();
        for entry in assignments.values() {
            for assignment in entry.get("assignments").and_then(Value::as_array).into_iter().flatten() {
                let routes = assignment.get("routes").and_then(Value::as_array).into_iter().flatten();
                let ports: BTreeSet<i64> = routes
                    .filter_map(|route| {
                        let id = Coerce::text(route.get("proxyId"));
                        if id.starts_with(PROXY_ID_PREFIX) {
                            id.rsplit(':').next().and_then(|tail| tail.parse().ok())
                        } else {
                            None
                        }
                    })
                    .collect();
                for port in ports {
                    *claims.entry(port).or_insert(0) += 1;
                }
            }
        }
        claims
    }

    /// An agent removed from its client, and the client with its last agent; the ports nothing else holds now.
    pub fn delete_agent(&self, body: &Value) -> Result<Value, AppError> {
        let (client_id, agent_id) = (Coerce::stripped(body.get("clientId")), Coerce::stripped(body.get("agentId")));
        if client_id.is_empty() {
            return Err(AppError::new("clientId is required"));
        }
        if agent_id.is_empty() {
            return Err(AppError::new("agentId is required"));
        }
        let answer = self.app.admin.change(|doc| -> Result<Value, AppError> {
            let mut topology = Topology::of(doc);
            let client = topology.clients().get_mut(&client_id).ok_or_else(|| AppError::with_status(format!("client not found: {client_id}"), 404))?;
            let agents = Coerce::list(client.get("agents"));
            let kept: Vec<Value> = agents.iter().filter(|agent| Coerce::text(agent.get("id")) != agent_id).cloned().collect();
            if kept.len() == agents.len() {
                return Err(AppError::with_status(format!("agent not found: {agent_id}"), 404));
            }
            let client_removed = kept.is_empty();
            Coerce::put(client, "agents", Value::Array(kept));
            let claims = Self::port_claims(topology.assignments());
            let mut held = BTreeSet::new();
            if let Some(entry) = topology.assignments().get_mut(&client_id)
                && let Some(rows) = entry.get("assignments").and_then(Value::as_array).cloned().filter(|rows| !rows.is_empty())
            {
                let is_agent = |row: &Value| Coerce::text(row.get("agentId")) == agent_id;
                for row in rows.iter().filter(|row| is_agent(row)) {
                    held.extend(row.get("routes").and_then(Value::as_array).into_iter().flatten().filter_map(Self::proxy_port));
                }
                Coerce::put(entry, "assignments", Value::Array(rows.into_iter().filter(|row| !is_agent(row)).collect()));
            }
            if client_removed {
                topology.clients().shift_remove(&client_id);
                topology.assignments().shift_remove(&client_id);
            }
            // absent-ok: a port nobody else claims is free to go.
            let freed: Vec<i64> = held.into_iter().filter(|port| claims.get(port).copied().unwrap_or(0) <= 1).collect();
            Ok(json!({"ok": true, "clientId": client_id, "agentId": agent_id, "freedPorts": freed, "clientRemoved": client_removed}))
        })?;
        self.app.save_admin();
        Ok(answer)
    }

    /// What an agent's block is named on the board.
    pub fn set_agent_alias(
        &self,
        host_id: Option<&Value>,
        agent_id: Option<&Value>,
        name: Option<&Value>,
    ) -> Result<Value, AppError> {
        let cut = |raw: Option<&Value>, most: usize| -> String {
            Coerce::strip(&Coerce::stripped(raw).chars().take(most).collect::<String>()).to_string()
        };
        let (host_id, agent_id, alias) = (cut(host_id, 120), cut(agent_id, 80), cut(name, 120));
        if host_id.is_empty() || agent_id.is_empty() {
            return Err(AppError::new("hostId and agentId are required"));
        }
        let key = format!("{host_id}::{agent_id}");
        self.app.admin.saving(|doc| {
            let store = AdminStore::topology(doc);
            if let Some(aliases) = store.entry("agentAliases".to_string()).or_insert_with(|| json!({})).as_object_mut() {
                if alias.is_empty() {
                    aliases.shift_remove(&key);
                } else {
                    aliases.insert(key.clone(), json!(alias));
                }
            }
        });
        Ok(json!({"hostId": host_id, "agentId": agent_id, "alias": alias}))
    }

    /// What a machine is named on the board.
    pub fn set_alias(&self, host_id: Option<&Value>, name: Option<&Value>) -> Result<Value, AppError> {
        let cut = |raw: Option<&Value>, most: usize| -> String {
            Coerce::strip(&Coerce::stripped(raw).chars().take(most).collect::<String>()).to_string()
        };
        let (host_id, alias) = (cut(host_id, 120), cut(name, 120));
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        self.app.admin.saving(|doc| {
            let mut topology = Topology::of(doc);
            if alias.is_empty() {
                topology.aliases().shift_remove(&host_id);
            } else {
                topology.aliases().insert(host_id.clone(), json!(alias));
            }
        });
        Ok(json!({"hostId": host_id, "alias": alias}))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_port_is_claimed_once_by_each_assignment() {
        let assignments = json!({"h": {"assignments": [
            {"routes": [{"proxyId": "skynet:proxy:5"}, {"proxyId": "skynet:proxy:5"}, {"proxyId": "other:9"}]},
            {"routes": [{"proxyId": "skynet:proxy:5"}, {"proxyId": "skynet:proxy:x"}]},
        ]}});
        let claims = ClientDesk::port_claims(assignments.as_object().unwrap());
        assert_eq!(claims, [(5, 2)].into());
    }
}
