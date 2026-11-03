//! The windows on the board: what a pool states to its clients, and what a port's model serves.

use super::server::TopologyServer;
use crate::app::App;
use crate::cloud::catalog::ModelCatalog;
use crate::common::cloud_pools::CloudPools;
use crate::common::window::Windows;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::cell::RefCell;
use std::collections::BTreeMap;

/// What a port's question is answered from. A proxy route that names a router reads its default output: the old graph of rules is drawn nowhere since 1.3.486, and no route of the live caravan reaches it.
pub struct PortQuestion;

impl PortQuestion {
    /// Where a question to the port goes: the route itself for a cloud one, else its router's default output laid over it.
    pub fn answer(route: &Value, config: &Value) -> Value {
        let mut resolved = route.clone();
        if Coerce::text(route.get("upstreamType")) == "cloud" {
            return resolved;
        }
        let router_id = Coerce::text(route.get("routerId"));
        if router_id.is_empty() {
            Coerce::put(&mut resolved, "unrouted", json!("unassigned"));
            return resolved;
        }
        let routers = config.get("routers").and_then(Value::as_array).into_iter().flatten();
        let mut routers = routers;
        let Some(router) = routers.find(|router| Coerce::str_of(router.get("id")) == router_id) else {
            Coerce::put(&mut resolved, "unrouted", json!("router missing"));
            return resolved;
        };
        let outputs = Coerce::list(router.get("outputs"));
        let default_id = Coerce::text(router.get("rules").and_then(|rules| rules.get("default")));
        let found = outputs.iter().find(|out| Coerce::str_of(out.get("id")) == default_id).or_else(|| outputs.first());
        let Some(out) = found else {
            Coerce::put(&mut resolved, "unrouted", json!("no output"));
            return resolved;
        };
        for key in ["upstreamType", "upstreamHost", "upstreamPort", "providerId", "upstreamModel"] {
            if let Some(said) = out.get(key) {
                Coerce::put(&mut resolved, key, said.clone());
            }
        }
        Coerce::put(&mut resolved, "routedOutputId", out.get("id").cloned().unwrap_or(Value::Null));
        resolved
    }

    /// What a question to the port reaches: "cloud", "llama" or "engine"; empty when it reaches nothing.
    pub fn reaches(resolved: &Value) -> String {
        let said = Coerce::text(resolved.get("upstreamType"));
        let kind = if said.is_empty() { "llama".to_string() } else { said };
        if Coerce::truthy(resolved.get("unrouted")) && kind != "cloud" {
            return String::new();
        }
        kind
    }
}

/// The window of each pool, with the catalogue read once per account.
pub struct PoolWindows<'app> {
    catalog: ModelCatalog<'app>,
    outputs: BTreeMap<String, Value>,
    catalogues: RefCell<BTreeMap<String, Map<String, Value>>>,
}

impl<'app> PoolWindows<'app> {
    /// The reading of `app`, with the routers' outputs of `proxy_config`.
    pub fn of(app: &'app App, proxy_config: &Value) -> Self {
        Self {
            catalog: ModelCatalog::of(app),
            outputs: Self::router_outputs(proxy_config),
            catalogues: RefCell::new(BTreeMap::new()),
        }
    }

    /// Output id → the routers' output.
    pub fn router_outputs(proxy_config: &Value) -> BTreeMap<String, Value> {
        let routers = proxy_config.get("routers").and_then(Value::as_array).into_iter().flatten();
        routers
            .flat_map(|router| router.get("outputs").and_then(Value::as_array).into_iter().flatten())
            .filter(|out| out.is_object() && Coerce::truthy(out.get("id")))
            .map(|out| (Coerce::str_of(out.get("id")), out.clone()))
            .collect()
    }

    fn named(&self, account: &str, model: &str) -> Option<i64> {
        let mut held = self.catalogues.borrow_mut();
        let rows = held.entry(account.to_string()).or_insert_with(|| {
            let entry = self.catalog.cached_models_entry(account);
            let models = entry.as_ref().and_then(|entry| entry.get("models")).and_then(Value::as_array).into_iter().flatten();
            models
                .filter(|row| row.is_object())
                .map(|row| (Coerce::str_of(row.get("id")), row.get("contextLength").cloned().unwrap_or(Value::Null)))
                .collect()
        });
        CloudPools::positive(rows.get(model))
    }

    /// The window a pool stands for.
    pub fn window(&self, pool: &Value) -> Option<i64> {
        let mut read = pool.clone();
        for step in read.get_mut("steps").and_then(Value::as_array_mut).into_iter().flatten() {
            if step.get("kind").and_then(Value::as_str).is_none_or(|kind| kind == "account")
                && Coerce::truthy(step.get("usageAccountId"))
            {
                let owner = step.get("usageAccountId").cloned().unwrap_or(Value::Null);
                Coerce::put(step, "accountId", owner);
            }
        }
        let local = |output: &str| self.outputs.get(output).and_then(|out| CloudPools::positive(out.get("contextLength")));
        CloudPools::window(&read, &|account, model| self.named(account, model), Some(&local))
    }
}

/// What the output a port answers `/v1/models` from serves.
pub struct RouteWindow;

impl RouteWindow {
    /// `(window, what it is the window of)`.
    pub fn facts(
        route: &Value,
        proxy_config: &Value,
        served: &BTreeMap<(String, i64), i64>,
        pools: &PoolWindows<'_>,
        by_id: &BTreeMap<String, Value>,
    ) -> (Option<i64>, Value) {
        let resolved = PortQuestion::answer(route, proxy_config);
        let kind = PortQuestion::reaches(&resolved);
        if kind.is_empty() {
            return (None, json!({"kind": "unrouted", "reason": Coerce::str_of(resolved.get("unrouted"))}));
        }
        if kind == "cloud" {
            let pool_id = Coerce::text(resolved.get("providerId"));
            if pool_id.is_empty() {
                return (None, json!({"kind": "account", "account": Coerce::text(resolved.get("cloudAccountId"))}));
            }
            let Some(pool) = by_id.get(&pool_id) else {
                return (None, json!({"kind": "unrouted", "reason": "pool missing"}));
            };
            let rows = pool.get("steps").and_then(Value::as_array).into_iter().flatten();
            let models: Vec<Value> = rows
                .filter(|step| {
                    step.get("enabled").is_none_or(|flag| Coerce::truthy(Some(flag)))
                        && step.get("kind").and_then(Value::as_str) != Some("open")
                })
                .map(|step| {
                    step.get("model")
                        .filter(|said| Coerce::truthy(Some(*said)))
                        .or_else(|| step.get("output"))
                        .cloned()
                        .unwrap_or(Value::Null)
                })
                .collect();
            let name = {
                let said = Coerce::text(pool.get("name"));
                if said.is_empty() { pool_id } else { said }
            };
            return (pools.window(pool), json!({"kind": "pool", "name": name, "models": models}));
        }
        let host = {
            let said = Coerce::text(resolved.get("upstreamHost"));
            if said.is_empty() { "127.0.0.1".to_string() } else { said }
        };
        // absent-ok: a route with no port has no window of its own.
        let port = TopologyServer::positive_int(resolved.get("upstreamPort")).unwrap_or(0);
        let model = Coerce::text(resolved.get("upstreamModel"));
        match kind.as_str() {
            "engine" => (None, json!({"kind": "engine", "model": model, "host": host, "port": port})),
            "machine" => {
                let outputs = PoolWindows::router_outputs(proxy_config);
                let out = outputs.get(&Coerce::text(resolved.get("routedOutputId")));
                (
                    TopologyServer::positive_int(out.and_then(|out| out.get("contextLength"))),
                    json!({"kind": "machine", "model": model, "host": host}),
                )
            }
            _ => (served.get(&(host.clone(), port)).copied(), json!({"kind": "cell", "host": host, "port": port})),
        }
    }

    /// The three windows on a proxy row.
    pub fn annotate(
        proxy: &mut Value,
        proxy_config: &Value,
        served: &BTreeMap<(String, i64), i64>,
        pools: &PoolWindows<'_>,
        by_id: &BTreeMap<String, Value>,
    ) {
        let (window, source) = Self::facts(proxy, proxy_config, served, pools, by_id);
        let (limit, prefer) = Windows::route_inputs(proxy);
        let refused = matches!(source.get("kind").and_then(Value::as_str), Some("unrouted" | "error"));
        let effective = if refused {
            None
        } else {
            Windows::effective(limit.map(|limit| json!(limit)).as_ref(), window.map(|window| json!(window)).as_ref(), prefer)
        };
        Coerce::put(proxy, "modelWindow", json!(window));
        Coerce::put(proxy, "modelWindowSource", source);
        Coerce::put(proxy, "effectiveWindow", json!(effective));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_cloud_port_answers_for_itself() {
        let route = json!({"upstreamType": "cloud", "providerId": "p"});
        let resolved = PortQuestion::answer(&route, &json!({}));
        assert_eq!(PortQuestion::reaches(&resolved), "cloud");
    }

    #[test]
    fn a_port_with_no_router_reaches_nothing() {
        let resolved = PortQuestion::answer(&json!({"port": 1}), &json!({}));
        assert_eq!(resolved["unrouted"], "unassigned");
        assert_eq!(PortQuestion::reaches(&resolved), "");
        let missing = PortQuestion::answer(&json!({"routerId": "r"}), &json!({"routers": []}));
        assert_eq!(missing["unrouted"], "router missing");
    }

    #[test]
    fn a_router_lays_its_default_output_over_the_route() {
        let config = json!({"routers": [{"id": "r", "rules": {"default": "b"}, "outputs": [{"id": "a", "upstreamType": "llama"}, {"id": "b", "upstreamType": "engine", "upstreamHost": "h", "upstreamPort": 5}]}]});
        let resolved = PortQuestion::answer(&json!({"routerId": "r"}), &config);
        assert_eq!(resolved["upstreamType"], "engine");
        assert_eq!(resolved["routedOutputId"], "b");
    }
}
