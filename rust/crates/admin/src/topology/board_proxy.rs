//! One proxy route as the board is handed it.

use super::server::TopologyServer;
use super::windows::{PoolWindows, RouteWindow};
use crate::app::App;
use crate::cloud::pools::PoolDesk;
use crate::common::entry::{BuiltinClient, ClientFields, EntryDoor};
use crate::domain::client_proxy::{PROXY_ID_PREFIX, ProxyRoute};
use crate::proxies::entry_settings::ConsumerAddress;
use crate::proxies::stats::ProxyStats;
use crate::store::topology::Topology;
use rules::{ClientDeny, Coerce, EntryModels};
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;

/// The proxy rows of this controller.
pub struct BoardProxies<'app> {
    app: &'app App,
}

impl<'app> BoardProxies<'app> {
    /// The rows of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn port_of(route: &Value) -> i64 {
        // absent-ok: `int(route.get("port") or 0)`: a route with no port holds none.
        Coerce::whole(route.get("port"))
    }

    /// `{proxy id: [(host, agent, role)]}`.
    pub fn holders(&self) -> BTreeMap<String, Vec<(String, String, String)>> {
        let assignments = self.app.admin.change(|doc| Topology::of(doc).assignments().clone());
        let mut held: BTreeMap<String, Vec<(String, String, String)>> = BTreeMap::new();
        for (host_id, entry) in &assignments {
            for row in entry.get("assignments").and_then(Value::as_array).into_iter().flatten() {
                let agent = Coerce::text(row.get("agentId"));
                for route in row.get("routes").and_then(Value::as_array).into_iter().flatten() {
                    let id = Coerce::text(route.get("proxyId"));
                    if id.is_empty() {
                        continue;
                    }
                    let role = {
                        let said = Coerce::text(route.get("role"));
                        if said.is_empty() { "primary".to_string() } else { said }
                    };
                    held.entry(id).or_default().push((host_id.clone(), agent.clone(), role));
                }
            }
        }
        held
    }

    fn row(
        route: &Value,
        holders: &BTreeMap<String, Vec<(String, String, String)>>,
        last_seen: &BTreeMap<i64, i64>,
        routers: &Map<String, Value>,
        address: &ConsumerAddress,
    ) -> Value {
        let port = Self::port_of(route);
        let served = if port != 0 { last_seen.get(&port).copied() } else { None };
        let id = format!("{PROXY_ID_PREFIX}{}", Coerce::str_of(route.get("port")));
        let mut proxy = route.clone();
        Coerce::put(&mut proxy, "id", json!(id));
        Coerce::put(&mut proxy, "endpoint", json!(address.of(port)));
        Coerce::put(&mut proxy, "keyTail", json!(EntryDoor::tail(&Coerce::text(route.get("apiKey")))));
        Coerce::put(
            &mut proxy,
            "upstreamId",
            json!(format!("skynet:llama-server:{}", Coerce::str_of(route.get("upstreamPort")))),
        );
        // absent-ok: a model that says no window shows none.
        Coerce::put(&mut proxy, "lastRequestAt", json!(served.unwrap_or(0)));
        if Coerce::text(route.get("kind")) == "consumer" {
            Coerce::take(&mut proxy, "apiKey");
        }
        let held: Vec<Value> = holders
            .get(&id)
            .into_iter()
            .flatten()
            .map(|(host, agent, role)| json!({"hostId": host, "agentId": agent, "role": role}))
            .collect();
        Coerce::put(&mut proxy, "holders", Value::Array(held));
        if let Some(router) = routers.get(&Coerce::text(route.get("routerId"))) {
            let outputs = Coerce::list(router.get("outputs"));
            let default_id = Coerce::text(router.get("rules").and_then(|rules| rules.get("default")));
            let out = outputs.iter().find(|out| Coerce::str_of(out.get("id")) == default_id).or_else(|| {
                outputs.iter().find(|out| {
                    let kind = Coerce::text(out.get("upstreamType"));
                    kind != "cloud"
                })
            });
            if let Some(out) = out.filter(|out| Coerce::int_or_zero(out.get("upstreamPort")).is_some_and(|port| port != 0)) {
                let host = Coerce::text(out.get("upstreamHost"));
                Coerce::put(
                    &mut proxy,
                    "resolvedUpstreamHost",
                    json!(if host.is_empty() { "127.0.0.1".to_string() } else { host }),
                );
                Coerce::put(&mut proxy, "resolvedUpstreamPort", json!(Coerce::int_or_zero(out.get("upstreamPort"))));
            }
        }
        proxy
    }

    /// Every route of `proxy_config` as the board is handed it.
    pub fn rows(&self, proxy_config: &Value, address: &ConsumerAddress) -> Vec<Value> {
        let holders = self.holders();
        let last_seen = ProxyStats::of(self.app).ports_last_seen(7);
        let routers: Map<String, Value> = proxy_config
            .get("routers")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .map(|router| (Coerce::str_of(router.get("id")), router.clone()))
            .collect();
        let routes = proxy_config.get("routes").and_then(Value::as_array).into_iter().flatten();
        routes.map(|route| Self::row(route, &holders, &last_seen, &routers, address)).collect()
    }

    /// Every client of the entry with what it is closed to and the models its key calls.
    pub fn annotate_consumers(&self, proxies: &mut [Value], models: Option<&EntryModels>) {
        for proxy in proxies.iter_mut().filter(|proxy| proxy.is_object() && Coerce::text(proxy.get("kind")) == "consumer") {
            for old in ["set", "setName", "pool"] {
                Coerce::take(proxy, old);
            }
            let deny = ClientDeny::clean(proxy.get(ClientDeny::FIELD));
            Coerce::put(proxy, ClientDeny::FIELD, json!(ClientFields::deny_list(proxy.get(ClientDeny::FIELD))));
            Coerce::put(proxy, "models", models.map_or(Value::Null, |models| json!(models.names(&deny))));
            if BuiltinClient::has_config(BuiltinClient::kind(proxy)) {
                Coerce::put(proxy, "offer", models.map_or(Value::Null, |models| Value::Array(models.offer(&deny))));
            }
        }
    }

    /// Every client with what it asked and was answered with an error, and what it called.
    pub fn annotate_tallies(&self, proxies: &mut [Value]) {
        let ports: Vec<i64> =
            proxies.iter().filter(|proxy| Coerce::text(proxy.get("kind")) == "consumer").map(Self::port_of).collect();
        let misses = self.app.tallies.misses(self.app, &ports);
        let calls = self.app.tallies.calls(self.app, &ports);
        for proxy in proxies.iter_mut().filter(|proxy| proxy.is_object() && Coerce::text(proxy.get("kind")) == "consumer") {
            let port = Self::port_of(proxy);
            if let Some(found) = &misses {
                Coerce::put(proxy, "misses", found.get(&port).cloned().unwrap_or_else(|| json!({"items": [], "more": 0})));
            }
            if let Some(found) = &calls {
                Coerce::put(proxy, "calls", found.get(&port).cloned().unwrap_or_else(|| json!([])));
            }
        }
    }

    /// Three windows on every proxy row.
    pub fn annotate_route_windows(&self, proxies: &mut [Value], proxy_config: &Value, server_obj: &Value) {
        let served = TopologyServer::served_windows(server_obj);
        let windows = PoolWindows::of(self.app, proxy_config);
        let Ok(pools) = PoolDesk::of(self.app).state() else {
            return;
        };
        let by_id: BTreeMap<String, Value> =
            pools.as_array().into_iter().flatten().map(|pool| (Coerce::text(pool.get("id")), pool.clone())).collect();
        for proxy in proxies.iter_mut().filter(|proxy| proxy.is_object()) {
            RouteWindow::annotate(proxy, proxy_config, &served, &windows, &by_id);
        }
    }

    /// The routers as the board reads them: each local output with its queue group.
    pub fn slot_groups(routers: Option<&Value>) -> Value {
        let rows = routers.and_then(Value::as_array).map_or(&[][..], Vec::as_slice);
        let copied: Vec<Value> = rows
            .iter()
            .map(|router| {
                if !router.is_object() {
                    return router.clone();
                }
                let outs: Vec<Value> = router
                    .get("outputs")
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten()
                    .map(|out| {
                        let kind = {
                            let said = Coerce::text(out.get("upstreamType"));
                            if said.is_empty() { "llama".to_string() } else { said }
                        };
                        if !out.is_object() || matches!(kind.as_str(), "cloud" | "engine") {
                            return out.clone();
                        }
                        let mut row = out.clone();
                        Coerce::put(&mut row, "slotGroup", json!(Self::group_key(out, &kind)));
                        row
                    })
                    .collect();
                let mut row = router.clone();
                Coerce::put(&mut row, "outputs", Value::Array(outs));
                row
            })
            .collect();
        Value::Array(copied)
    }

    /// One queue per upstream llama-server, and one per model of a machine's entry.
    fn group_key(route: &Value, kind: &str) -> String {
        const UPSTREAM_HOST: &str = "127.0.0.1";
        const UPSTREAM_PORT: i64 = 8080;
        let host = {
            let said = Coerce::text(route.get("upstreamHost"));
            if said.is_empty() { UPSTREAM_HOST.to_string() } else { said }
        };
        let port =
            route.get("upstreamPort").filter(|said| Coerce::truthy(Some(*said))).and_then(Coerce::int).unwrap_or(UPSTREAM_PORT);
        if kind == "machine" {
            return format!("{host}:{port}/{}", Coerce::text(route.get("upstreamModel")));
        }
        format!("{host}:{port}")
    }

    /// The URL of a port, by this controller's address.
    pub fn port_url(&self, port: i64) -> String {
        ProxyRoute::port_url(&self.app.paths.topology_server_ip, port)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_local_output_gets_its_queue_group() {
        let routers = json!([{"outputs": [
            {"id": "a", "upstreamType": "llama", "upstreamHost": "h", "upstreamPort": 5},
            {"id": "b", "upstreamType": "cloud"},
            {"id": "c", "upstreamType": "machine", "upstreamHost": "h", "upstreamPort": 5, "upstreamModel": "m"},
        ]}, 5]);
        let shown = BoardProxies::slot_groups(Some(&routers));
        assert_eq!(shown[0]["outputs"][0]["slotGroup"], "h:5");
        assert!(shown[0]["outputs"][1].get("slotGroup").is_none());
        assert_eq!(shown[0]["outputs"][2]["slotGroup"], "h:5/m");
        assert_eq!(shown[1], 5);
    }

    #[test]
    fn a_consumer_row_hides_its_key_and_says_its_holders() {
        let route = json!({"port": 5, "kind": "consumer", "apiKey": "secret-key"});
        let address = ConsumerAddress::new(&json!({}), "h", Some(true));
        let holders = [("skynet:proxy:5".to_string(), vec![("a".to_string(), "b".to_string(), "primary".to_string())])].into();
        let row = BoardProxies::row(&route, &holders, &[(5, 9)].into(), &Map::new(), &address);
        assert!(row.get("apiKey").is_none());
        assert_eq!(row["holders"], json!([{"hostId": "a", "agentId": "b", "role": "primary"}]));
        assert_eq!(row["lastRequestAt"], 9);
        assert_eq!(row["id"], "skynet:proxy:5");
    }
}
