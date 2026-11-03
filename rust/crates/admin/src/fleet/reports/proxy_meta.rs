//! The proxy routes' words about their clients, kept in step with what the machines report.

use super::*;

impl<'app> FleetReads<'app> {
    /// Each proxy route's label, client and role in sync with the live assignments, the reliable link from proxy to agent; whether anything changed.
    pub fn reconcile_proxy_metadata(&self) -> Result<bool, AppError> {
        let (assignments, clients) = self.app.admin.change(|doc| {
            let mut topology = Topology::of(doc);
            (topology.assignments().clone(), topology.clients().clone())
        });
        let (port_meta, contested) = Self::port_meta(&assignments, &clients);
        if port_meta.is_empty() {
            return Ok(false);
        }
        let config = ProxiesConfig::of(self.app);
        let mut payload = config.read_payload();
        let mut changed = false;
        let auto_keys = ["contextLength", "contextAuto", "modelName", "modelNameAuto"];
        for route in payload.get_mut("routes").and_then(Value::as_array_mut).into_iter().flatten() {
            let Some(port) = route.get("port").and_then(Coerce::int) else {
                continue;
            };
            let meta = port_meta.get(&port);
            if contested.contains(&port) || meta.is_none() {
                for key in auto_keys {
                    changed = Coerce::take(route, key).is_some() || changed;
                }
                continue;
            }
            let Some(meta) = meta.filter(|meta| Coerce::truthy(meta.get("name"))) else {
                continue;
            };
            for key in ["clientId", "role"] {
                if Coerce::text(route.get(key)) != Coerce::text(meta.get(key)) {
                    Coerce::put(route, key, meta.get(key).cloned().unwrap_or(Value::Null));
                    changed = true;
                }
            }
            for key in auto_keys {
                match meta.get(key).filter(|want| !want.is_null()) {
                    None => changed = Coerce::take(route, key).is_some() || changed,
                    Some(want) if route.get(key) != Some(want) => {
                        Coerce::put(route, key, want.clone());
                        changed = true;
                    }
                    Some(_) => {}
                }
            }
        }
        if changed {
            config.write_payload(payload)?;
        }
        Ok(changed)
    }

    pub(super) fn port_meta(
        assignments: &Map<String, Value>,
        clients: &Map<String, Value>,
    ) -> (BTreeMap<i64, Value>, BTreeSet<i64>) {
        const PREFIX: &str = crate::domain::client_proxy::PROXY_ID_PREFIX;
        let (mut meta, mut contested) = (BTreeMap::new(), BTreeSet::new());
        for (host_id, entry) in assignments {
            let client = clients.get(host_id);
            let client_name = Coerce::stripped(client.and_then(|client| client.get("name")));
            // absent-ok: a client with no list has no agents.
            let agents = client.and_then(|client| client.get("agents")).and_then(Value::as_array).cloned().unwrap_or_default();
            for assignment in entry.get("assignments").and_then(Value::as_array).into_iter().flatten() {
                let agent_id = assignment.get("agentId");
                let agent = agents.iter().find(|agent| agent.get("id") == agent_id);
                let agent_name = {
                    let named = Coerce::stripped(agent.and_then(|agent| agent.get("name")));
                    if named.is_empty() { Coerce::stripped(agent_id) } else { named }
                };
                let name = if client_name.is_empty() { agent_name } else { client_name.clone() };
                for route in assignment.get("routes").and_then(Value::as_array).into_iter().flatten() {
                    let Some(port) =
                        Coerce::text(route.get("proxyId")).strip_prefix(PREFIX).and_then(|tail| tail.parse::<i64>().ok())
                    else {
                        continue;
                    };
                    if meta.contains_key(&port) {
                        contested.insert(port);
                        continue;
                    }
                    let role = {
                        let said = Coerce::text(route.get("role"));
                        if said.is_empty() { "primary".to_string() } else { said }
                    };
                    let model_name: Option<String> =
                        route.get("modelName").filter(|said| Coerce::truthy(Some(*said))).map(|said| {
                            let cut: String = Coerce::str_of(Some(said)).chars().take(120).collect();
                            Coerce::strip(&cut).to_string()
                        });
                    let flag = |key: &str| Coerce::truthy(route.get(key)).then_some(true);
                    meta.insert(
                        port,
                        json!({
                            "clientId": host_id, "role": role, "name": name,
                            "contextLength": route.get("contextLength"),
                            "modelName": model_name.filter(|word| !word.is_empty()),
                            "modelNameAuto": flag("modelNameAuto"),
                            "contextAuto": flag("contextAuto"),
                        }),
                    );
                }
            }
        }
        (meta, contested)
    }
}
