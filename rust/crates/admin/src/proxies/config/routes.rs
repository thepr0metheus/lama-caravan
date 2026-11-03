//! The proxy's routes one at a time: their ports, their keys, their settings.

use super::*;

/// What a patch of one route is held against.
pub(super) struct PatchContext<'read> {
    pub(super) entry_open: bool,
    pub(super) routers: &'read BTreeSet<String>,
    pub(super) others: &'read [Value],
    pub(super) target: i64,
}

impl<'app> ProxiesConfig<'app> {
    /// Every number the fleet must not hand out, from ALL of its own registers.
    /// Every port the fleet holds: a route's, a cell's, an excluded one.
    pub fn all_taken_ports(&self, routes: &[Value]) -> BTreeSet<i64> {
        let mut used = self.app.used_cell_ports();
        used.extend(routes.iter().filter_map(|route| Coerce::int_or_zero(route.get("port"))));
        if let Ok(config) = self.load() {
            used.extend(Coerce::int_or_zero(config.get("entry").and_then(|entry| entry.get("port"))));
        }
        used.remove(&0);
        used
    }

    /// Whether something already listens here.
    pub fn port_is_listening(port: i64) -> bool {
        ListeningPorts::read().busy(port)
    }

    /// The smallest free port in the proxy range: a consumer's number.
    pub fn next_free_port(&self, routes: &[Value]) -> Result<i64, AppError> {
        let used = self.all_taken_ports(routes);
        let ports = self.app.paths.proxy_ports;
        let mut port = ports.base;
        while used.contains(&port) || Self::port_is_listening(port) {
            port += 1;
            if port > ports.upper {
                return Err(AppError::with_status(format!("no free proxy port left in the proxy range {ports}"), 500));
            }
        }
        Ok(port)
    }

    /// Deletes ANY proxy port from the board, with its router wiring.
    pub fn delete_route(&self, port: Option<&Value>, force: bool) -> Result<Value, AppError> {
        let port = port.and_then(Coerce::int).ok_or_else(|| AppError::new("port must be a number"))?;
        let payload = self.load()?;
        let routes = Coerce::list(payload.get("routes"));
        let is_it = |route: &Value| route.get("port").and_then(Value::as_i64) == Some(port);
        let Some(target) = routes.iter().find(|route| is_it(route)).cloned() else {
            return Err(AppError::with_status(format!("no proxy route on port {port}"), 404));
        };
        if !force {
            let bound = self.bound_to(port);
            if !bound.is_empty() {
                return Err(AppError::with_status(
                    format!("port {port} is still assigned to {} — point the agent elsewhere first", bound.join(", ")),
                    409,
                ));
            }
        }
        let kept: Vec<Value> = routes.iter().filter(|route| !is_it(route)).cloned().collect();
        self.save(Value::Array(kept), payload.get("routers").cloned(), None)?;
        Ok(json!({"deleted": port, "label": Coerce::text(target.get("label"))}))
    }

    /// Who is pointed at a port, as "host/agent".
    pub(super) fn bound_to(&self, port: i64) -> Vec<String> {
        let end = format!(":{port}");
        self.app.admin.change(|doc| {
            let mut topology = Topology::of(doc);
            let mut bound = Vec::new();
            for (host, row) in topology.assignments().iter() {
                for entry in row.get("assignments").and_then(Value::as_array).into_iter().flatten() {
                    for route in entry.get("routes").and_then(Value::as_array).into_iter().flatten() {
                        if Coerce::text(route.get("proxyId")).ends_with(&end) {
                            bound.push(format!("{host}/{}", Coerce::str_of(entry.get("agentId"))));
                        }
                    }
                }
            }
            bound
        })
    }

    /// The proxy's policy.
    pub fn set_policy(&self, policy: &Value) -> Result<Value, AppError> {
        if policy.get(ClientNameWord::KEY).is_some() && !ClientNameWord::acceptable(policy.get(ClientNameWord::KEY)) {
            return Err(AppError::new(format!(
                "{} must be up to {} printable Latin characters",
                ClientNameWord::KEY,
                ClientNameWord::LONGEST
            )));
        }
        let mut payload = self.load()?;
        let mut merged = Coerce::fields(payload.get("policy").unwrap_or(&Value::Null));
        merged.extend(Coerce::fields(policy));
        if let Value::Object(fields) = &mut payload {
            fields.insert("policy".to_string(), RouterDsl::policy(Some(&Value::Object(merged))));
        }
        self.write_payload(payload.clone())?;
        Ok(payload)
    }

    /// A consumer's key, given where none was.
    pub fn new_route_key() -> Result<String, AppError> {
        let bytes = Randomness::bytes(24).ok_or_else(|| AppError::with_status("the system gives no random bytes", 500))?;
        Ok(format!("lcv1_{}", bytes.iter().map(|byte| format!("{byte:02x}")).collect::<String>()))
    }

    /// A route's own settings.
    pub fn set_route_policy(&self, port: Option<&Value>, patch: &Value) -> Result<Value, AppError> {
        let target = port.and_then(Coerce::int).ok_or_else(|| {
            let words = if port.is_none_or(Value::is_null) {
                "int() argument must be a string, a bytes-like object or a real number, not 'NoneType'".to_string()
            } else {
                format!("invalid literal for int(): {}", Coerce::str_of(port))
            };
            AppError::with_status(words, 500)
        })?;
        let mut payload = self.load()?;
        let entry_open =
            Coerce::int_or_zero(payload.get("entry").and_then(|entry| entry.get("port"))).is_some_and(|port| port != 0);
        let routers: BTreeSet<String> = payload
            .get("routers")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .map(|router| Coerce::text(router.get("id")))
            .collect();
        let others = Coerce::list(payload.get("routes"));
        let routes = payload
            .get_mut("routes")
            .and_then(Value::as_array_mut)
            .ok_or_else(|| AppError::with_status("proxy route not found", 404))?;
        let mut found = false;
        for route in routes.iter_mut().filter(|route| route.get("port").and_then(Value::as_i64) == Some(target)) {
            found = true;
            let context = PatchContext { entry_open, routers: &routers, others: &others, target };
            self.patch_route(route, patch, &context)?;
        }
        if !found {
            return Err(AppError::with_status("proxy route not found", 404));
        }
        KeyAudit::enforce(routes)?;
        self.write_payload(payload.clone())?;
        Ok(payload)
    }

    fn patch_label(
        &self,
        fields: &mut serde_json::Map<String, Value>,
        patch: &Value,
        is_consumer: bool,
        context: &PatchContext<'_>,
    ) -> Result<(), AppError> {
        if patch.get("label").is_some() {
            let label = Coerce::first_letters(&Coerce::stripped(patch.get("label")), 80).to_string();
            let label = if !label.is_empty() && is_consumer {
                self.app.clean_client_name(&label, context.others, Some(context.target))?
            } else {
                label
            };
            if !label.is_empty() {
                fields.insert("label".to_string(), json!(label));
            }
        }
        Ok(())
    }

    fn patch_mode(fields: &mut serde_json::Map<String, Value>, patch: &Value) -> Result<(), AppError> {
        if patch.get("mode").is_some() {
            let mode = if Coerce::truthy(patch.get("mode")) {
                Coerce::stripped(patch.get("mode")).to_lowercase()
            } else {
                "open".to_string()
            };
            if !matches!(mode.as_str(), "open" | "paused" | "drain") {
                return Err(AppError::new("mode must be open, paused, or drain"));
            }
            fields.insert("mode".to_string(), json!(mode));
        }
        Ok(())
    }

    pub(super) fn patch_route(&self, route: &mut Value, patch: &Value, context: &PatchContext<'_>) -> Result<(), AppError> {
        let is_consumer = route.get("kind").and_then(Value::as_str) == Some("consumer");
        let Value::Object(fields) = route else {
            return Ok(());
        };
        self.patch_label(fields, patch, is_consumer, context)?;
        Self::patch_mode(fields, patch)?;
        if patch.get("priority").is_some() {
            let priority =
                Coerce::int_or_zero(patch.get("priority")).ok_or_else(|| AppError::with_status("priority is no number", 500))?;
            fields.insert("priority".to_string(), json!(priority.clamp(0, 100)));
        }
        if patch.get("preemptible").is_some() {
            fields.insert("preemptible".to_string(), json!(Coerce::truthy(patch.get("preemptible"))));
        }
        if patch.get("portClosed").is_some() {
            if Coerce::truthy(patch.get("portClosed")) {
                if !context.entry_open {
                    return Err(AppError::with_status(
                        "the entry is off — open it before closing a port, or the agent has no way in",
                        409,
                    ));
                }
                fields.insert("portClosed".to_string(), json!(true));
            } else {
                return Err(ProxiesConfig::own_ports_gone());
            }
        }
        Self::patch_upstream(fields, patch)?;
        if patch.get("cloudFallbackProviderId").is_some() {
            fields.insert("cloudFallbackProviderId".to_string(), json!(Coerce::stripped(patch.get("cloudFallbackProviderId"))));
        }
        if patch.get("routerId").is_some() {
            if is_consumer {
                return Err(AppError::new(
                    "a client of the entry calls a pool or a model by its name, not a router: close on its card in Routing what it may not call",
                ));
            }
            let router_id = Coerce::stripped(patch.get("routerId"));
            if !router_id.is_empty() && !context.routers.contains(&router_id) {
                return Err(AppError::new("unknown router"));
            }
            fields.insert("routerId".to_string(), json!(router_id));
        }
        for key in ["cloudFallbackPct", "priorityPreemptPct", "queueAbortPct"] {
            match patch.get(key) {
                None => {}
                Some(Value::Null) => {
                    fields.shift_remove(key);
                }
                Some(said) => {
                    let number = Coerce::int(said).ok_or_else(|| AppError::with_status(format!("{key} is no number"), 500))?;
                    fields.insert(key.to_string(), json!(number.clamp(0, 100)));
                }
            }
        }
        Ok(())
    }

    pub(super) fn patch_upstream(fields: &mut Map<String, Value>, patch: &Value) -> Result<(), AppError> {
        if patch.get("upstreamType").is_some() {
            let kind = if Coerce::truthy(patch.get("upstreamType")) {
                Coerce::stripped(patch.get("upstreamType")).to_lowercase()
            } else {
                "llama".to_string()
            };
            if !matches!(kind.as_str(), "llama" | "cloud") {
                return Err(AppError::new("upstreamType must be llama or cloud"));
            }
            fields.insert("upstreamType".to_string(), json!(kind));
            if kind == "cloud" {
                let provider = Coerce::stripped(patch.get("providerId"));
                if provider.is_empty() {
                    return Err(AppError::new("providerId required for cloud upstream"));
                }
                fields.insert("providerId".to_string(), json!(provider));
            } else {
                fields.insert("providerId".to_string(), json!(""));
            }
        } else if patch.get("providerId").is_some() {
            fields.insert("providerId".to_string(), json!(Coerce::stripped(patch.get("providerId"))));
        }
        Ok(())
    }

    /// Replaces the router list: the UI sends the full array.
    pub fn set_routers(&self, routers: &Value, revision: Option<&Value>) -> Result<Value, AppError> {
        let _held = self.locked();
        self.check_revision("routers", revision)?;
        let mut payload = self.load()?;
        let mut routes = payload.get("routes").and_then(Value::as_array).cloned();
        let normalized = Self::normalize_routers(Some(routers), routes.as_mut())?;
        if let Value::Object(fields) = &mut payload {
            fields.insert("routers".to_string(), Value::Array(normalized));
            if let Some(routes) = routes {
                fields.insert("routes".to_string(), Value::Array(routes));
            }
        }
        self.write_payload(payload.clone())?;
        Ok(payload)
    }
}
