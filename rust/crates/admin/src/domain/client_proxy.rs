//! An agent's assignment and its routes. The normalizer REBUILDS the record from scratch, so a field it doesn't name quietly disappears on the next save. The field list lives here, in one place: an added field survives a save at every writer at once, or at none of them.

use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;

/// What a proxy port is called inside the caravan.
pub const PROXY_ID_PREFIX: &str = "skynet:proxy:";

/// One role of one agent: which proxy port it uses.
#[derive(Debug, Clone, PartialEq)]
pub struct ProxyRoute {
    /// Its role, "primary" by default.
    pub role: String,
    /// The port's id; empty is more honest than a missing key.
    pub proxy_id: String,
    /// The address as it was when the port was bound.
    pub endpoint: String,
    /// The window the operator set FOR THIS consumer. `None` means unset; zero and garbage also: a client would read zero as a real limit.
    pub context_length: Option<i64>,
    /// "Take whatever the model reports": stored only when turned on or off by hand.
    pub context_auto: Option<bool>,
    /// The name this port advertises its model under.
    pub model_name: Option<String>,
    /// "Open the lock": advertise the model under its own name.
    pub model_name_auto: Option<bool>,
}

impl ProxyRoute {
    /// The window the operator set, and whether the model's own figure is taken: what is not a positive number, and a switch that is off, are not stored.
    pub fn set_context(&mut self, window: Option<&Value>, auto: bool) {
        self.context_length = Self::positive(window);
        self.context_auto = auto.then_some(true);
    }

    /// The name the port advertises its model under; empty is none.
    pub fn set_model(&mut self, name: &str, auto: bool) {
        self.model_name = (!name.is_empty()).then(|| name.to_string());
        self.model_name_auto = auto.then_some(true);
    }

    fn word(value: Option<&Value>) -> String {
        if Coerce::truthy(value) { Coerce::stripped(value) } else { String::new() }
    }

    fn positive(value: Option<&Value>) -> Option<i64> {
        let value = value.filter(|value| !matches!(value, Value::Null | Value::Bool(false)) && value.as_str() != Some(""))?;
        Coerce::int(value).filter(|number| *number > 0)
    }

    fn option_flag(value: Option<&Value>) -> Option<bool> {
        value.filter(|value| !value.is_null()).map(|value| Coerce::truthy(Some(value)))
    }

    /// A route from its parts, as they come.
    pub fn of(raw: &Value) -> Self {
        let role = Self::word(raw.get("role"));
        let model_name = Coerce::truthy(raw.get("modelName"))
            .then(|| Coerce::first_letters(&Coerce::stripped(raw.get("modelName")), 120).to_string())
            .filter(|name| !name.is_empty());
        Self {
            role: if role.is_empty() { "primary".to_string() } else { role },
            proxy_id: Self::word(raw.get("proxyId")),
            endpoint: Self::word(raw.get("endpoint")),
            context_length: Self::positive(raw.get("contextLength")),
            context_auto: Self::option_flag(raw.get("contextAuto")),
            model_name,
            model_name_auto: Self::option_flag(raw.get("modelNameAuto")),
        }
    }

    /// The address a client calls a caravan port at: the one format, for the bind, the board's proxy rows and the agents' routes alike.
    pub fn port_url(server_ip: &str, port: i64) -> String {
        format!("http://{server_ip}:{port}/v1")
    }

    /// A route to an issued port: the one place that assembles the `proxyId`/`endpoint` pair.
    pub fn for_port(role: &str, port: i64, server_ip: &str) -> Self {
        Self::of(
            &json!({"role": role, "proxyId": format!("{PROXY_ID_PREFIX}{port}"), "endpoint": Self::port_url(server_ip, port)}),
        )
    }

    /// The port out of the id, if it's there. 0 means "unknown", not "port zero".
    pub fn port(&self) -> i64 {
        let tail = self.proxy_id.rsplit(':').next();
        let digits = tail.filter(|tail| !tail.is_empty() && tail.chars().all(|letter| letter.is_ascii_digit()));
        // absent-ok: 0 says "unknown", as this method's word.
        digits.and_then(|tail| tail.parse().ok()).unwrap_or(0)
    }

    /// Where this route's port is reached NOW: `endpoint` is the address as it was when the port was bound, and the controller's address can change under it. A route that names no port of ours keeps the address it was stored with.
    pub fn address(&self, server_ip: &str) -> String {
        if self.port() != 0 && !Coerce::strip(server_ip).is_empty() {
            return Self::port_url(server_ip, self.port());
        }
        self.endpoint.clone()
    }

    /// A route as a client sends it: refused when it names no address.
    pub fn from_raw(raw: &Value) -> Result<Self, AppError> {
        if !raw.is_object() {
            return Err(AppError::new("route must be an object"));
        }
        let route = Self::of(raw);
        if route.endpoint.is_empty() {
            return Err(AppError::new("route.endpoint is required"));
        }
        Ok(route)
    }

    /// Settings that were never set aren't written at all: a route the operator never touched keeps the three-key shape it always had.
    pub fn to_json(&self) -> Value {
        let mut out = Map::new();
        out.insert("role".to_string(), json!(self.role));
        out.insert("proxyId".to_string(), json!(self.proxy_id));
        out.insert("endpoint".to_string(), json!(self.endpoint));
        if let Some(length) = self.context_length {
            out.insert("contextLength".to_string(), json!(length));
        }
        if let Some(auto) = self.context_auto {
            out.insert("contextAuto".to_string(), json!(auto));
        }
        if let Some(name) = &self.model_name {
            out.insert("modelName".to_string(), json!(name));
        }
        if let Some(auto) = self.model_name_auto {
            out.insert("modelNameAuto".to_string(), json!(auto));
        }
        Value::Object(out)
    }
}

/// Where one agent goes: its routes, one per role.
#[derive(Debug, Clone, PartialEq)]
pub struct AgentAssignment {
    /// The agent.
    pub agent_id: String,
    /// Its routes.
    pub routes: Vec<ProxyRoute>,
}

impl AgentAssignment {
    /// An assignment of no routes yet.
    pub fn new(agent_id: Option<&Value>) -> Result<Self, AppError> {
        let id = ProxyRoute::word(agent_id);
        if id.is_empty() {
            return Err(AppError::new("assignment.agentId is required"));
        }
        Ok(Self { agent_id: id, routes: Vec::new() })
    }

    /// An assignment as a client sends it.
    pub fn from_raw(raw: &Value) -> Result<Self, AppError> {
        if !raw.is_object() {
            return Err(AppError::new("assignment must be an object"));
        }
        let said = raw.get("routes").filter(|routes| Coerce::truthy(Some(*routes)));
        let list = match said {
            None => &[][..],
            Some(routes) => {
                routes.as_array().map(Vec::as_slice).ok_or_else(|| AppError::new("assignment.routes must be a list"))?
            }
        };
        let mut seen = BTreeSet::new();
        let mut routes = Vec::with_capacity(list.len());
        for item in list {
            let route = ProxyRoute::from_raw(item)?;
            if !seen.insert(route.role.clone()) {
                return Err(AppError::new(format!("duplicate route role: {}", route.role)));
            }
            routes.push(route);
        }
        let mut assignment = Self::new(raw.get("agentId"))?;
        assignment.routes = routes;
        Ok(assignment)
    }

    /// The route of a role.
    pub fn route(&self, role: &str) -> Option<&ProxyRoute> {
        self.routes.iter().find(|route| route.role == role)
    }

    /// The route of a role, to change it.
    pub fn route_mut(&mut self, role: &str) -> Option<&mut ProxyRoute> {
        self.routes.iter_mut().find(|route| route.role == role)
    }

    /// Takes a role's route away.
    pub fn remove_route(&mut self, role: &str) {
        self.routes.retain(|route| route.role != role);
    }

    /// Sets the route for its role: replaces an existing one, else adds it. What moves is LIVENESS, where the agent is reached: settings the operator set on this role are not cancelled by a port move.
    pub fn set_route(&mut self, route: ProxyRoute) {
        let Some(existing) = self.routes.iter_mut().find(|said| said.role == route.role) else {
            self.routes.push(route);
            return;
        };
        existing.proxy_id = route.proxy_id;
        existing.endpoint = route.endpoint;
        if route.context_length.is_some() {
            existing.context_length = route.context_length;
        }
        if route.context_auto.is_some() {
            existing.context_auto = route.context_auto;
        }
        if route.model_name.is_some() {
            existing.model_name = route.model_name;
        }
        if route.model_name_auto.is_some() {
            existing.model_name_auto = route.model_name_auto;
        }
    }

    /// The record.
    pub fn to_json(&self) -> Value {
        json!({"agentId": self.agent_id, "routes": self.routes.iter().map(ProxyRoute::to_json).collect::<Vec<_>>()})
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_route_keeps_three_keys_until_it_is_told_more() {
        let route = ProxyRoute::for_port("primary", 23001, "10.0.0.1");
        assert_eq!(
            route.to_json(),
            json!({"role": "primary", "proxyId": "skynet:proxy:23001", "endpoint": "http://10.0.0.1:23001/v1"})
        );
        assert_eq!(route.port(), 23001);
        assert_eq!(route.address("10.0.0.9"), "http://10.0.0.9:23001/v1");
        assert_eq!(route.address(""), "http://10.0.0.1:23001/v1");
    }

    #[test]
    fn zero_and_garbage_are_no_limit() {
        for said in [json!(0), json!("x"), json!(""), json!(false), json!(-5), Value::Null] {
            assert_eq!(ProxyRoute::of(&json!({"contextLength": said})).context_length, None);
        }
        assert_eq!(ProxyRoute::of(&json!({"contextLength": "4096"})).context_length, Some(4096));
    }

    #[test]
    fn a_port_move_keeps_what_the_operator_set() {
        let mut assignment = AgentAssignment::new(Some(&json!("a"))).unwrap();
        assignment.set_route(ProxyRoute::of(
            &json!({"role": "primary", "proxyId": "skynet:proxy:1", "endpoint": "e1", "contextLength": 100, "modelName": "m"}),
        ));
        assignment.set_route(ProxyRoute::of(&json!({"role": "primary", "proxyId": "skynet:proxy:2", "endpoint": "e2"})));
        let route = assignment.route("primary").unwrap();
        assert_eq!(
            (route.proxy_id.as_str(), route.endpoint.as_str(), route.context_length, route.model_name.as_deref()),
            ("skynet:proxy:2", "e2", Some(100), Some("m"))
        );
        assert_eq!(assignment.routes.len(), 1);
    }

    #[test]
    fn a_role_twice_and_no_address_are_refused() {
        let twice = json!({"agentId": "a", "routes": [{"endpoint": "e"}, {"endpoint": "f"}]});
        assert_eq!(AgentAssignment::from_raw(&twice).unwrap_err().message, "duplicate route role: primary");
        assert_eq!(
            AgentAssignment::from_raw(&json!({"agentId": "a", "routes": [{}]})).unwrap_err().message,
            "route.endpoint is required"
        );
        assert_eq!(AgentAssignment::from_raw(&json!({"routes": []})).unwrap_err().message, "assignment.agentId is required");
    }
}
