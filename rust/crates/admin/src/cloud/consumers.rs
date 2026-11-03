//! A client of the entry, made on the board. A client's only way in is the entry, under its own key, and it sees every
//! pool and model but what the board closed to it.

use super::data::CloudData;
use crate::app::App;
use crate::common::cloud_pools::CloudPools;
use crate::common::entry::{BuiltinClient, ClientFields};
use crate::proxies::config::{KeyAudit, ProxiesConfig};
use rules::{AppError, ClientDeny, Coerce, EntryModels};
use serde_json::{Value, json};
use std::collections::BTreeSet;

/// The board's clients of the entry (the owner, 2026-10-11).
pub struct ConsumerDesk<'app> {
    app: &'app App,
}

impl<'app> ConsumerDesk<'app> {
    const KIND: &'static str = "consumer";
    const NAME_MAX: usize = 80;
    const MIGRATION: &'static str = "entry-sets-gone-2026-10";
    const OLD_FIELDS: [&'static str; 3] = ["set", "pool", "models"];

    /// The desk of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn config(&self) -> ProxiesConfig<'app> {
        ProxiesConfig::of(self.app)
    }

    fn port_of(route: &Value) -> i64 {
        // absent-ok: `int(route.get("port") or 0)`: a route that names no port is no client's.
        Coerce::whole(route.get("port"))
    }

    fn is_consumer(route: &Value) -> bool {
        Coerce::text(route.get("kind")) == Self::KIND
    }

    fn routes_of(payload: &Value) -> Vec<Value> {
        Coerce::list(payload.get("routes"))
    }

    fn entry_port(payload: &Value) -> i64 {
        // absent-ok: an entry that names no port is off.
        Coerce::int_or_zero(payload.get("entry").and_then(|entry| entry.get("port"))).unwrap_or(0)
    }

    fn kinds_word() -> String {
        BuiltinClient::KINDS.iter().map(|row| row.0).collect::<Vec<_>>().join(", ")
    }

    fn new_route(&self, label: &str, port: i64, kind: &str) -> Result<Value, AppError> {
        let mut route = json!({"label": label, "port": port, "kind": Self::KIND});
        if !kind.is_empty() {
            Coerce::put(&mut route, BuiltinClient::FIELD, json!(kind));
        }
        Coerce::put(&mut route, "apiKey", json!(ProxiesConfig::new_route_key()?));
        Coerce::put(&mut route, "portClosed", json!(true));
        Coerce::put(&mut route, ClientDeny::FIELD, json!([]));
        Coerce::put(&mut route, "upstreamType", json!("cloud"));
        Coerce::put(&mut route, "routerId", json!(""));
        Coerce::put(&mut route, "mode", json!("open"));
        Ok(route)
    }

    /// A new client, closed to nothing.
    pub fn create(&self, name: Option<&Value>, kind: &str) -> Result<Value, AppError> {
        if !kind.is_empty() && !BuiltinClient::KINDS.iter().any(|row| row.0 == kind) {
            return Err(AppError::new(format!("kind must be one of {}", Self::kinds_word())));
        }
        let mut payload = self.config().load()?;
        if Self::entry_port(&payload) == 0 {
            return Err(AppError::with_status(
                "the entry is off — set up the entry first: a consumer's only way in is the entry",
                409,
            ));
        }
        let mut routes = Self::routes_of(&payload);
        if !kind.is_empty() && !BuiltinClient::many(kind) && BuiltinClient::find(&routes, kind).is_some() {
            return Err(AppError::with_status(
                format!("{} is one client: its row on the board is the one to connect", BuiltinClient::name(kind)),
                409,
            ));
        }
        let name = if !kind.is_empty() && Coerce::stripped(name).is_empty() {
            Self::builtin_name(&routes, kind, None)
        } else {
            Self::clean_name(name, &routes, None)?
        };
        let route = self.new_route(&name, self.config().next_free_port(&routes)?, kind)?;
        routes.push(route.clone());
        KeyAudit::enforce(&routes)?;
        Coerce::put(&mut payload, "routes", Value::Array(routes));
        self.config().write_payload(payload)?;
        Ok(json!({"port": route.get("port"), "name": name, "key": route.get("apiKey"), (ClientDeny::FIELD): []}))
    }

    /// What a client is closed to from now on: the whole list, `[]` opening everything.
    pub fn set_deny(&self, port: Option<&Value>, deny: Option<&Value>) -> Result<Value, AppError> {
        let Some(deny) = deny.and_then(Value::as_array) else {
            return Err(AppError::new("deny must be a list of keys: pool:<id>, model:<place>, account:<id>, host:<id>"));
        };
        let mut payload = self.config().load()?;
        let at = Self::consumer_at(&payload, port)?;
        let raw = Value::Array(deny.clone());
        let cleaned = ClientFields::deny_list(Some(&raw));
        let bad: Vec<String> = deny
            .iter()
            .filter(|key| !key.as_str().is_some_and(|key| cleaned.iter().any(|kept| kept == Coerce::strip(key))))
            .map(|key| Coerce::str_of(Some(key)).chars().take(80).collect())
            .collect();
        if !bad.is_empty() {
            let shown: Vec<String> = bad.into_iter().take(5).collect();
            return Err(AppError::new(format!("not a key of a pool, a model, an account or a machine: {}", shown.join(", "))));
        }
        let cloud = CloudData::of(self.app);
        let known = cloud.live_models(payload.get("routers")).choices();
        let mut names: BTreeSet<String> = BTreeSet::new();
        for list in ["pools", "models"] {
            names.extend(known.get(list).and_then(Value::as_array).into_iter().flatten().map(|row| Coerce::text(row.get("key"))));
        }
        names.extend(known.get("sources").and_then(Value::as_array).into_iter().flatten().map(|row| Coerce::text(Some(row))));
        let routes = Self::routes_of(&payload);
        let kept: Vec<String> =
            routes.get(at).map_or_else(Vec::new, |route| ClientFields::deny_list(route.get(ClientDeny::FIELD)));
        let unknown: Vec<&String> = cleaned.iter().filter(|key| !names.contains(*key) && !kept.contains(key)).collect();
        if !unknown.is_empty() {
            let shown: Vec<&str> = unknown.iter().take(5).map(|key| key.as_str()).collect();
            return Err(AppError::new(format!(
                "the board has nothing under {} — reload the board and close it again",
                shown.join(", ")
            )));
        }
        let port = Self::with_route(&mut payload, at, |route| {
            Coerce::put(route, ClientDeny::FIELD, json!(cleaned));
            route.get("port").cloned()
        });
        self.config().write_payload(payload)?;
        Ok(json!({"port": port, (ClientDeny::FIELD): cleaned}))
    }

    fn with_route<R>(payload: &mut Value, at: usize, change: impl FnOnce(&mut Value) -> Option<R>) -> Option<R> {
        payload.get_mut("routes").and_then(Value::as_array_mut).and_then(|routes| routes.get_mut(at)).and_then(change)
    }

    /// A new key for a consumer, answered this once.
    pub fn new_key(&self, port: Option<&Value>) -> Result<Value, AppError> {
        let mut payload = self.config().load()?;
        let at = Self::consumer_at(&payload, port)?;
        let key = ProxiesConfig::new_route_key()?;
        let (port, name) = Self::with_route(&mut payload, at, |route| {
            Coerce::put(route, "apiKey", json!(key));
            Some((route.get("port").cloned(), Coerce::text(route.get("label"))))
        })
        .unwrap_or((None, String::new()));
        KeyAudit::enforce(&Self::routes_of(&payload))?;
        self.config().write_payload(payload)?;
        Ok(json!({"port": port, "name": name, "key": key}))
    }

    /// The built-in client of `kind`, made when the caravan has none (the owner, 2026-10-27). The entry it needs is opened by `open_entry`.
    pub fn ensure_builtin(
        &self,
        open_entry: Option<&dyn Fn() -> Result<Value, AppError>>,
        kind: &str,
    ) -> Result<Option<Value>, AppError> {
        let mut payload = self.config().load()?;
        if BuiltinClient::find(&Self::routes_of(&payload), kind).is_some() {
            return Ok(None);
        }
        let (mut opened, mut refused) = (Value::Null, String::new());
        if Self::entry_port(&payload) == 0
            && let Some(open) = open_entry
        {
            match open() {
                Ok(answer) => opened = answer.get("port").cloned().unwrap_or(Value::Null),
                Err(error) => refused = error.message,
            }
            payload = self.config().load()?;
        }
        let mut routes = Self::routes_of(&payload);
        let name = Self::builtin_name(&routes, kind, None);
        let route = self.new_route(&name, self.config().next_free_port(&routes)?, kind)?;
        let port = route.get("port").cloned();
        routes.push(route);
        KeyAudit::enforce(&routes)?;
        Coerce::put(&mut payload, "routes", Value::Array(routes));
        self.config().write_payload(payload)?;
        Ok(Some(json!({"port": port, "name": name, "kind": kind, "entry": opened, "entryRefused": refused})))
    }

    /// The kind's name, or "… 2", 3… when a client of that name is there (`but`, a port, not counted).
    fn builtin_name(routes: &[Value], kind: &str, but: Option<i64>) -> String {
        let taken: BTreeSet<String> = routes
            .iter()
            .filter(|route| Self::is_consumer(route) && Some(Self::port_of(route)) != but)
            .map(|route| EntryModels::key_of(&Coerce::text(route.get("label"))))
            .collect();
        let base = BuiltinClient::name(kind);
        let (mut name, mut number) = (base.to_string(), 2);
        while taken.contains(&EntryModels::key_of(&name)) {
            name = format!("{base} {number}");
            number += 1;
        }
        name
    }

    /// The consumer's name: a client is told apart by it on the board and in the journal.
    pub fn clean_name(raw: Option<&Value>, routes: &[Value], own_port: Option<i64>) -> Result<String, AppError> {
        let name: String = Coerce::stripped(raw).chars().take(Self::NAME_MAX).collect();
        let name = Coerce::strip(&name).to_string();
        if name.is_empty() {
            return Err(AppError::new("name is required: the consumer's name, as the board and the journal show it"));
        }
        let wanted = EntryModels::key_of(&name);
        // absent-ok: `int(own_port or 0)`: no port of its own is no route's.
        let own = own_port.unwrap_or(0);
        let taken = routes
            .iter()
            .filter(|route| Self::is_consumer(route) && Self::port_of(route) != own)
            .any(|route| EntryModels::key_of(&Coerce::text(route.get("label"))) == wanted);
        if taken {
            return Err(AppError::with_status(format!("a consumer named {name} exists — give this one another name"), 409));
        }
        Ok(name)
    }

    /// The move to clients without sets (the owner, 2026-10-27), once: what each client had, and the sets that go.
    pub fn migrate(&self) -> Result<Option<Value>, AppError> {
        let cloud = CloudData::of(self.app);
        let mut data = cloud.load();
        let done = data.get("migrations").and_then(Value::as_array).into_iter().flatten();
        if done.filter_map(Value::as_str).any(|word| word == Self::MIGRATION) {
            return Ok(None);
        }
        let mut payload = self.config().read_payload();
        let pool_rows = CloudPools::new(&data, None).all();
        let sets: Vec<Value> =
            Coerce::list(data.get("sets")).into_iter().filter(|row| row.is_object() && Coerce::truthy(row.get("id"))).collect();
        let (mut clients, mut changed) = (Vec::new(), false);
        for route in payload.get_mut("routes").and_then(Value::as_array_mut).into_iter().flatten() {
            if !route.is_object() || !Self::is_consumer(route) {
                continue;
            }
            let had = Self::had_before(route, &sets, &pool_rows);
            let old = Self::OLD_FIELDS.iter().any(|field| route.get(field).is_some());
            if old || !route.get(ClientDeny::FIELD).is_some_and(Value::is_array) {
                for field in Self::OLD_FIELDS {
                    Coerce::take(route, field);
                }
                let cleaned = ClientFields::deny_list(route.get(ClientDeny::FIELD));
                Coerce::put(route, ClientDeny::FIELD, json!(cleaned));
                changed = true;
            }
            clients.push(json!({"name": Coerce::text(route.get("label")), "port": Self::port_of(route), "had": had}));
        }
        if changed {
            self.config().write_payload(payload)?;
        }
        let gone: Vec<Value> = sets
            .iter()
            .map(|set| {
                let pools: Vec<String> = Coerce::list(set.get("pools"))
                    .iter()
                    .map(|id| {
                        let id = Coerce::str_of(Some(id));
                        Self::pool_name_in(&pool_rows, &id).unwrap_or(id)
                    })
                    .collect();
                json!({"name": Self::set_name(set), "pools": pools})
            })
            .collect();
        Coerce::take(&mut data, "sets");
        CloudData::with_migrations(&mut data, &[Self::MIGRATION]);
        cloud.save(&data)?;
        Ok(Some(json!({"clients": clients, "sets": gone})))
    }

    fn pool_name_in(pools: &[Value], id: &str) -> Option<String> {
        pools.iter().find(|pool| Coerce::text(pool.get("id")) == id).map(|pool| {
            let name = Coerce::stripped(pool.get("name"));
            if name.is_empty() { Coerce::text(pool.get("id")) } else { name }
        })
    }

    fn set_name(set: &Value) -> String {
        let name = Coerce::stripped(set.get("name"));
        if name.is_empty() { Coerce::str_of(set.get("id")) } else { name }
    }

    /// What a client called before: its set's name, or its pool's.
    fn had_before(route: &Value, sets: &[Value], pools: &[Value]) -> String {
        if route.get("set").is_some() {
            let said = Coerce::text(route.get("set"));
            return sets.iter().find(|set| Coerce::str_of(set.get("id")) == said).map_or_else(String::new, Self::set_name);
        }
        if route.get("pool").is_some() {
            // absent-ok: a route with no number names no pool.
            return Self::pool_name_in(pools, &Coerce::text(route.get("pool"))).unwrap_or_default();
        }
        String::new()
    }

    /// Where the consumer on `port` stands in the routes.
    fn consumer_at(payload: &Value, port: Option<&Value>) -> Result<usize, AppError> {
        let target = port.and_then(Coerce::int).ok_or_else(|| AppError::new("port must be a number"))?;
        let routes = Self::routes_of(payload);
        let at = routes.iter().position(|route| Self::port_of(route) == target);
        at.filter(|at| routes.get(*at).is_some_and(Self::is_consumer))
            .ok_or_else(|| AppError::with_status(format!("no consumer has the number {target}"), 404))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_name_is_trimmed_and_unique_without_case() {
        let routes =
            [json!({"kind": "consumer", "port": 1, "label": "Hermes"}), json!({"kind": "service", "port": 2, "label": "other"})];
        assert_eq!(ConsumerDesk::clean_name(Some(&json!("  a ")), &routes, None).unwrap(), "a");
        assert_eq!(ConsumerDesk::clean_name(Some(&json!("other")), &routes, None).unwrap(), "other");
        assert_eq!(ConsumerDesk::clean_name(Some(&json!("hermes")), &routes, None).unwrap_err().status, 409);
        assert_eq!(ConsumerDesk::clean_name(Some(&json!("hermes")), &routes, Some(1)).unwrap(), "hermes");
        assert_eq!(ConsumerDesk::clean_name(Some(&json!(" ")), &routes, None).unwrap_err().status, 400);
    }

    #[test]
    fn a_built_in_name_is_made_free() {
        let routes = [json!({"kind": "consumer", "port": 1, "label": "opencode"})];
        assert_eq!(ConsumerDesk::builtin_name(&routes, "opencode", None), "opencode 2");
        assert_eq!(ConsumerDesk::builtin_name(&routes, "opencode", Some(1)), "opencode");
        assert_eq!(ConsumerDesk::builtin_name(&[], "open-webui", None), "Open WebUI");
    }
}
