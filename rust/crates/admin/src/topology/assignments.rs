//! The agents' roles on the proxy's ports: the assignments.

use crate::app::App;
use crate::domain::client_proxy::{AgentAssignment, ProxyRoute};
use crate::fleet::reports::FleetReads;
use crate::proxies::entry_settings::ConsumerAddress;
use crate::store::topology::Topology;
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};

/// The assignments of this controller.
pub struct Assignments<'app> {
    app: &'app App,
}

impl<'app> Assignments<'app> {
    /// The assignments of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// The stored assignments as the board is handed them: each route at the address it has now.
    pub fn at_current_address(assignments: &Map<String, Value>, address: &ConsumerAddress, server_ip: &str) -> Value {
        let mut out = Map::new();
        for (host_id, entry) in assignments {
            if !entry.is_object() {
                out.insert(host_id.clone(), entry.clone());
                continue;
            }
            let rows: Vec<Value> = entry
                .get("assignments")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .map(|row| {
                    let Some(raw_routes) = row.get("routes").and_then(Value::as_array).filter(|_| row.is_object()) else {
                        return row.clone();
                    };
                    let routes: Vec<Value> = raw_routes
                        .iter()
                        .map(|raw| {
                            let Ok(route) = ProxyRoute::from_raw(raw) else {
                                return raw.clone();
                            };
                            let endpoint = if route.port() != 0 { address.of(route.port()) } else { route.address(server_ip) };
                            let mut shown = raw.clone();
                            Coerce::put(&mut shown, "endpoint", json!(endpoint));
                            shown
                        })
                        .collect();
                    let mut shown = row.clone();
                    Coerce::put(&mut shown, "routes", Value::Array(routes));
                    shown
                })
                .collect();
            let mut shown = entry.clone();
            Coerce::put(&mut shown, "assignments", Value::Array(rows));
            out.insert(host_id.clone(), shown);
        }
        Value::Object(out)
    }

    fn rows_of(&self, host_id: &str) -> Vec<Value> {
        self.app.admin.change(|doc| {
            let mut topology = Topology::of(doc);
            topology
                .assignments()
                .get(host_id)
                .and_then(|entry| entry.get("assignments"))
                .and_then(Value::as_array)
                .cloned()
                // absent-ok: a client with no row has no agents.
                .unwrap_or_default()
        })
    }

    fn required(payload: &Value, role_default: Option<&str>) -> Result<(String, String, String), AppError> {
        let host_id = Coerce::stripped(payload.get("hostId"));
        let agent_id = Coerce::stripped(payload.get("agentId"));
        let said_role = Coerce::stripped(payload.get("role"));
        let role = if said_role.is_empty() { role_default.unwrap_or("").to_string() } else { said_role };
        if host_id.is_empty() || agent_id.is_empty() {
            return Err(AppError::new("hostId and agentId are required"));
        }
        Ok((host_id, agent_id, role))
    }

    /// An agent pointed at a proxy port by hand: gone with the ports themselves. A client has no port of its own since 2026-11-02 and no
    /// number since 2026-11-07 (the owner): an agent calls the entry with its own key, as a client of it.
    pub fn bind(&self, _payload: &Value) -> Result<Value, AppError> {
        Err(AppError::with_status(
            "an agent is pointed at no port: it calls the entry with its own key — make it a client with ＋ in the Clients column",
            410,
        ))
    }

    fn edit_route(
        &self,
        host_id: &str,
        agent_id: &str,
        change: impl FnOnce(&mut AgentAssignment) -> Result<(), AppError>,
    ) -> Result<Value, AppError> {
        let mut rows = self.rows_of(host_id);
        let row = rows.iter_mut().find(|row| row.get("agentId").and_then(Value::as_str) == Some(agent_id));
        let row = row.ok_or_else(|| AppError::with_status(format!("no assignment for agent {agent_id} on {host_id}"), 404))?;
        let mut assignment = AgentAssignment::from_raw(row)?;
        change(&mut assignment)?;
        *row = assignment.to_json();
        self.apply(&json!({"hostId": host_id, "assignments": rows}))
    }

    /// The context window for one consumer: one agent's role.
    pub fn set_context(&self, payload: &Value) -> Result<Value, AppError> {
        let (host_id, agent_id, role) = Self::required(payload, Some("primary"))?;
        if !matches!(role.as_str(), "primary" | "fallback") {
            return Err(AppError::new(format!("role must be \"primary\" or \"fallback\", got \"{role}\"")));
        }
        let window = payload.get("contextLength").cloned();
        let auto = Coerce::truthy(payload.get("contextAuto"));
        let (agent, held_role) = (agent_id.clone(), role.clone());
        self.edit_route(&host_id, &agent_id, move |assignment| {
            let route = assignment
                .route_mut(&held_role)
                .ok_or_else(|| AppError::with_status(format!("agent {agent} has no {held_role} route"), 404))?;
            route.set_context(window.as_ref(), auto);
            Ok(())
        })
    }

    /// An agent's role removed.
    pub fn remove_route(&self, payload: &Value) -> Result<Value, AppError> {
        let both = Self::required(payload, None);
        let (host_id, agent_id, role) = both
            .ok()
            .filter(|(_, _, role)| !role.is_empty())
            .ok_or_else(|| AppError::new("hostId, agentId and role are required"))?;
        let (agent, held_role) = (agent_id.clone(), role.clone());
        self.edit_route(&host_id, &agent_id, move |assignment| {
            if assignment.route(&held_role).is_none() {
                return Err(AppError::with_status(format!("agent {agent} has no {held_role} route"), 404));
            }
            assignment.remove_route(&held_role);
            Ok(())
        })
    }

    /// The name a port advertises its model under, for one agent's role.
    pub fn set_model(&self, payload: &Value) -> Result<Value, AppError> {
        let (host_id, agent_id, role) = Self::required(payload, Some("primary"))?;
        let name: String = Coerce::stripped(payload.get("modelName")).chars().take(120).collect();
        let name = Coerce::strip(&name).to_string();
        let auto = Coerce::truthy(payload.get("modelNameAuto"));
        let (agent, held_role) = (agent_id.clone(), role.clone());
        self.edit_route(&host_id, &agent_id, move |assignment| {
            let route = assignment
                .route_mut(&held_role)
                .ok_or_else(|| AppError::with_status(format!("agent {agent} has no {held_role} route"), 404))?;
            route.set_model(&name, auto);
            Ok(())
        })
    }

    /// A machine's assignments from now on.
    pub fn apply(&self, payload: &Value) -> Result<Value, AppError> {
        let host_id = Coerce::stripped(payload.get("hostId"));
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        let rows =
            payload.get("assignments").and_then(Value::as_array).ok_or_else(|| AppError::new("assignments must be a list"))?;
        let normalized: Vec<Value> =
            rows.iter().map(|row| AgentAssignment::from_raw(row).map(|read| read.to_json())).collect::<Result<_, _>>()?;
        let row = json!({"hostId": host_id, "assignments": normalized});
        self.app.admin.saving(|doc| {
            Topology::of(doc).assignments().insert(host_id.clone(), row.clone());
        });
        // A port whose label could not be rewritten is rewritten on the next change.
        drop(FleetReads::of(self.app).reconcile_proxy_metadata());
        Ok(row)
    }
}
