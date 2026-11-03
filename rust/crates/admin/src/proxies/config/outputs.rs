//! The routers' outputs: rebuilt from what stands on the board, and followed when a cell moves.

use super::*;

impl<'app> ProxiesConfig<'app> {
    /// One auto-output per local server.
    pub(super) fn local_outputs(server: &Value) -> Vec<Value> {
        let (mut outs, mut seen) = (Vec::new(), BTreeSet::new());
        for row in server.get("llamaServers").and_then(Value::as_array).into_iter().flatten() {
            let port = Coerce::str_of(row.get("port"));
            if !Coerce::truthy(row.get("port")) || !seen.insert(port.clone()) {
                continue;
            }
            let (host, node) = if Coerce::truthy(row.get("isController")) {
                ("127.0.0.1".to_string(), CONTROLLER_HOST_ID.to_string())
            } else {
                let address = Coerce::stripped(row.get("clientIp"));
                if address.is_empty() {
                    continue;
                }
                (address.clone(), address)
            };
            let model = Coerce::text(row.get("model"));
            // absent-ok: an empty name has no last word.
            let model = model.rsplit('/').next().unwrap_or_default();
            let what = if model.is_empty() { Coerce::text(row.get("cellLabel")) } else { model.to_string() };
            let label = if what.is_empty() { format!(":{port}") } else { format!("{what} :{port}") };
            let mut out = json!({"id": format!("srv:{port}"), "label": label, "target": format!("{node}:llama-server:{port}"), "upstreamHost": host, "upstreamPort": row.get("port").and_then(Coerce::int), "upstreamType": "llama", "providerId": ""});
            if let Value::Object(fields) = &mut out {
                fields.extend(ModelFacts::cell_facts(row));
                if Self::STANDING_PHASES.contains(&Coerce::text(row.get("phase")).as_str()) {
                    fields.insert("stopped".to_string(), json!(true));
                }
            }
            outs.push(out);
        }
        outs
    }

    /// The router output of one pool.
    pub fn pool_output(pool: &Value) -> Value {
        let id = Coerce::str_of(pool.get("id"));
        let name = if Coerce::truthy(pool.get("name")) { Coerce::text(pool.get("name")) } else { id.clone() };
        json!({"id": format!("cb:{id}"), "label": format!("☁ {name}"), "target": format!("pool:{id}"), "upstreamHost": "", "upstreamPort": 0, "upstreamType": "cloud", "providerId": id})
    }

    /// Outputs are AUTO-derived from the available providers; whether anything changed.
    pub fn sync_router_outputs(
        routers: &mut [Value],
        server: &Value,
        pools: &[Value],
        engine_outputs: &[Value],
        machine_outputs: &[Value],
    ) -> Result<bool, AppError> {
        let cloud: Vec<Value> = pools.iter().map(Self::pool_output).collect();
        let raw = Self::local_outputs(server)
            .into_iter()
            .chain(engine_outputs.iter().cloned())
            .chain(machine_outputs.iter().cloned())
            .chain(cloud);
        let desired = raw.map(|row| RouterDsl::output(&row)).collect::<Result<Vec<_>, _>>()?;
        let ids: BTreeSet<String> = desired.iter().map(|row| Coerce::text(row.get("id"))).collect();
        let mut changed = false;
        for router in routers.iter_mut().filter(|router| router.is_object()) {
            if router.get("outputs").and_then(Value::as_array).map_or(&[][..], Vec::as_slice) != desired.as_slice() {
                router["outputs"] = Value::Array(desired.clone());
                changed = true;
            }
            let Value::Object(fields) = router else {
                continue;
            };
            let rules = fields.entry("rules".to_string()).or_insert_with(|| json!({}));
            let Value::Object(rules) = rules else {
                continue;
            };
            let dormant = Coerce::text(rules.get("dormantDefault"));
            if !dormant.is_empty() && ids.contains(&dormant) {
                rules.insert("default".to_string(), json!(dormant));
                rules.shift_remove("dormantDefault");
                changed = true;
            }
            if !rules.get("default").and_then(Value::as_str).is_some_and(|said| ids.contains(said)) {
                let old = Coerce::text(rules.get("default"));
                if ["srv:", "cb:", "eng:", "mm:"].iter().any(|kind| old.starts_with(kind))
                    && !Coerce::truthy(rules.get("dormantDefault"))
                {
                    rules.insert("dormantDefault".to_string(), json!(old));
                }
                let local = desired
                    .iter()
                    .find(|row| row.get("upstreamType").and_then(Value::as_str) != Some("cloud"))
                    .or_else(|| desired.first());
                rules.insert("default".to_string(), json!(local.map_or_else(String::new, |row| Coerce::text(row.get("id")))));
                changed = true;
            }
        }
        Ok(changed)
    }

    /// The router list, kept consistent with the proxy routes.
    pub fn normalize_routers(raw: Option<&Value>, routes: Option<&mut Vec<Value>>) -> Result<Vec<Value>, AppError> {
        let ports = routes.as_deref().map(|routes| PortInputs::new(routes));
        let mut by_id: Vec<(String, Value)> = Vec::new();
        for router in raw.and_then(Value::as_array).into_iter().flatten() {
            let cut = ports.as_ref().map_or_else(|| router.clone(), |ports| ports.forget_absent(router));
            let row = RouterDsl::router(&cut)?;
            let id = Coerce::text(row.get("id"));
            if !by_id.iter().any(|(said, _)| *said == id) {
                by_id.push((id, row));
            }
        }
        let default_id = RouterDsl::DEFAULT_ROUTER_ID;
        if !by_id.iter().any(|(id, _)| id == default_id) {
            by_id.push((default_id.to_string(), RouterDsl::router(&json!({"id": default_id, "name": "Default"}))?));
        }
        let known: BTreeSet<String> = by_id.iter().map(|(id, _)| id.clone()).collect();
        let empty: Vec<Value> = Vec::new();
        let mut derived_routes = empty;
        if let Some(routes) = routes {
            for route in routes.iter_mut().filter(|route| route.is_object()) {
                if route.get("kind").and_then(Value::as_str) == Some("consumer") {
                    route["routerId"] = json!("");
                }
                let router_id = route.get("routerId");
                if router_id.and_then(Value::as_str) != Some("")
                    && !router_id.and_then(Value::as_str).is_some_and(|id| known.contains(id))
                {
                    route["routerId"] = json!(default_id);
                }
            }
            derived_routes.clone_from(routes);
        }
        let derived = PortInputs::new(&derived_routes);
        let mut first = Vec::with_capacity(by_id.len());
        let mut rest = Vec::with_capacity(by_id.len());
        for pair in by_id {
            if pair.0 == default_id {
                first.push(pair);
            } else {
                rest.push(pair);
            }
        }
        first.extend(rest);
        let mut ordered = Vec::with_capacity(first.len());
        for (id, mut router) in first {
            if let Value::Object(fields) = &mut router {
                fields.insert("inputs".to_string(), json!(derived.of_router(&id)));
            }
            ordered.push(router);
        }
        Ok(ordered)
    }

    /// Follows a renamed output id everywhere a router can point at it.
    pub fn remap_output_refs(&self, old_id: &str, new_id: &str) -> Result<bool, AppError> {
        let mut payload = self.load()?;
        let new_port = new_id.strip_prefix("srv:").and_then(|port| port.parse::<i64>().ok());
        let mut changed = false;
        for router in payload.get_mut("routers").and_then(Value::as_array_mut).into_iter().flatten() {
            for out in router.get_mut("outputs").and_then(Value::as_array_mut).into_iter().flatten() {
                if out.get("id").and_then(Value::as_str) == Some(old_id) {
                    out["id"] = json!(new_id);
                    if let Some(port) = new_port {
                        out["upstreamPort"] = json!(port);
                    }
                    changed = true;
                }
            }
            let moved =
                RouterOutputRefs::new(router).rewrite(&|said| if said == old_id { new_id.to_string() } else { said.to_string() });
            changed = changed || moved != 0;
        }
        if changed {
            self.save(payload.get("routes").cloned().unwrap_or_else(|| json!([])), payload.get("routers").cloned(), None)?;
        }
        Ok(changed)
    }

    /// Swaps two output ids everywhere a router points at either: each cable follows its own cell.
    pub fn swap_output_refs(&self, id_a: &str, id_b: &str) -> Result<bool, AppError> {
        let mut payload = self.load()?;
        let port_of = |id: &str| id.strip_prefix("srv:").and_then(|port| port.parse::<i64>().ok());
        let (port_a, port_b) = (port_of(id_a), port_of(id_b));
        let mut changed = false;
        for router in payload.get_mut("routers").and_then(Value::as_array_mut).into_iter().flatten() {
            for out in router.get_mut("outputs").and_then(Value::as_array_mut).into_iter().flatten() {
                let said = Coerce::text(out.get("id"));
                let (new_id, port) = if said == id_a {
                    (id_b, port_b)
                } else if said == id_b {
                    (id_a, port_a)
                } else {
                    continue;
                };
                out["id"] = json!(new_id);
                if let Some(port) = port {
                    out["upstreamPort"] = json!(port);
                }
                changed = true;
            }
            let moved = RouterOutputRefs::new(router).rewrite(&|said| {
                if said == id_a {
                    id_b.to_string()
                } else if said == id_b {
                    id_a.to_string()
                } else {
                    said.to_string()
                }
            });
            changed = changed || moved != 0;
        }
        if changed {
            self.save(payload.get("routes").cloned().unwrap_or_else(|| json!([])), payload.get("routers").cloned(), None)?;
        }
        Ok(changed)
    }
}
