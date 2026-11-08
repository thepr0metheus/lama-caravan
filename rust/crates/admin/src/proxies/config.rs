//! `agent-proxies.json`, read and changed. A write goes through one door: cloud fallback worked out again, routers re-derived from the routes, the graph protected.

use super::client_ids::{ClientIds, FormerPorts};
use super::dsl::RouterDsl;
use super::service::{ListeningPorts, Services};
use crate::app::App;
use crate::common::entry::{BuiltinClient, ClientNameWord, EntryDoor};
use net::{Randomness, Sha256};
use rules::{AppError, ClientDeny, Coerce, PythonJson};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::sync::{Mutex, MutexGuard, PoisonError};

mod checks;
pub use checks::KeyAudit;
pub use checks::PortInputs;
pub use checks::ProxyRevisions;
pub use checks::StaleCopy;

mod outputs;

mod routes;

/// The lock a list's check and its write stand under.
#[derive(Default)]
pub struct ProxyLock {
    held: Mutex<()>,
}

/// The document's view.
pub struct ProxiesConfig<'app> {
    app: &'app App,
}

impl<'app> ProxiesConfig<'app> {
    /// The refusal of a client's own port: the proxy listens on the entry alone (the owner, 2026-11-02), and a client has no number
    /// since 2026-11-07, so nothing is left to open or close.
    pub fn own_ports_gone() -> AppError {
        AppError::with_status("a client comes in through the entry with its key: it has no port of its own", 410)
    }

    const OWNED_FIELDS: [&'static str; 6] =
        ["cloudFallbackPct", "priorityPreemptPct", "queueAbortPct", "apiKey", ClientDeny::FIELD, BuiltinClient::FIELD];

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn locked(&self) -> MutexGuard<'_, ()> {
        self.app.proxy_lock.held.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// The document as stored, schema-upgraded.
    pub fn read_payload(&self) -> Value {
        let default = json!({"routes": [], "policy": RouterDsl::policy(None), "routers": [], "stopRequests": []});
        self.app.proxies.payload(default, &self.app.stamp())
    }

    /// The one door a write goes through.
    pub fn write_payload(&self, mut payload: Value) -> Result<(), AppError> {
        if let Some(routes) = payload.get("routes").and_then(Value::as_array) {
            let stored = self.read_payload();
            BuiltinClient::audit(stored.get("routes").and_then(Value::as_array).map_or(&[][..], Vec::as_slice), routes)?;
        }
        if let Some(routes) = payload.get_mut("routes").and_then(Value::as_array_mut) {
            RouterDsl::recompute_cloud_fallback(routes);
        }
        if payload.get("routers").is_some() || Coerce::truthy(payload.get("routes")) {
            let mut routes = payload.get("routes").and_then(Value::as_array).cloned();
            // A router that does not read leaves the routers as they came: the write's safety net is below, and it may not refuse.
            if let Ok(routers) = Self::normalize_routers(payload.get("routers"), routes.as_mut())
                && let Value::Object(fields) = &mut payload
            {
                fields.insert("routers".to_string(), Value::Array(routers));
                if let Some(routes) = routes {
                    fields.insert("routes".to_string(), Value::Array(routes));
                }
            }
        }
        let protected = self.app.proxies.protect_graph(payload, &self.app.stamp());
        self.app.proxies.write(&protected).map_err(|error| AppError::with_status(error.to_string(), 500))
    }

    /// The current version of each list.
    pub fn revisions(&self) -> Value {
        ProxyRevisions::of(&self.read_payload())
    }

    fn check_revision(&self, name: &str, seen: Option<&Value>) -> Result<(), AppError> {
        let seen = seen.filter(|seen| Coerce::truthy(Some(*seen)));
        if seen
            .is_some_and(|seen| Some(Coerce::str_of(Some(seen)).as_str()) != self.revisions().get(name).and_then(Value::as_str))
        {
            return Err(StaleCopy::refusal(name));
        }
        Ok(())
    }

    /// The document, normalised.
    pub fn load(&self) -> Result<Value, AppError> {
        self.load_from(&self.read_payload())
    }

    /// A reading, normalised.
    pub fn load_from(&self, payload: &Value) -> Result<Value, AppError> {
        let (mut cleaned, mut seen) = (Vec::new(), BTreeSet::new());
        for route in payload.get("routes").and_then(Value::as_array).into_iter().flatten() {
            let Ok(row) = RouterDsl::route(route) else {
                continue;
            };
            if seen.insert(ClientIds::of(&row)) {
                cleaned.push(row);
            }
        }
        let routers = Self::normalize_routers(payload.get("routers"), Some(&mut cleaned))?;
        let stops: Vec<Value> = payload
            .get("stopRequests")
            .and_then(Value::as_array)
            .map_or_else(Vec::new, |rows| rows.iter().skip(rows.len().saturating_sub(100)).cloned().collect());
        let mut loaded = json!({"routes": cleaned, "policy": RouterDsl::policy(payload.get("policy")), "routers": routers, "stopRequests": stops, "entry": EntryDoor::clean(payload.get("entry"))});
        Self::keep_former_ports(&mut loaded, payload);
        Ok(loaded)
    }

    /// Saves the whole list of routes. `revision`: the version the page was shown.
    pub fn save(&self, routes: Value, routers: Option<Value>, revision: Option<&Value>) -> Result<Value, AppError> {
        let payload = {
            let _held = self.locked();
            self.check_revision("routes", revision)?;
            self.write_routes(&routes, routers)?
        };
        Services::of(self.app).start_proxy();
        Ok(payload)
    }

    /// The numbers the clients had, as the document keeps them, carried into a payload made anew: history the journal is read by.
    fn keep_former_ports(payload: &mut Value, from: &Value) {
        let former = FormerPorts::of(from);
        if former != FormerPorts::default() {
            Coerce::put(payload, FormerPorts::FIELD, former.json());
        }
    }

    /// The posted route with the stored values of the fields only their own doors set.
    fn kept(route: &Value, by_id: &BTreeMap<String, &Value>) -> Value {
        if !route.is_object() {
            return route.clone();
        }
        let Some(stored) = by_id.get(&ClientIds::of(route)) else {
            return route.clone();
        };
        let mut out = Coerce::fields(route);
        for key in Self::OWNED_FIELDS {
            if let (Some(value), false) = (stored.get(key), out.contains_key(key)) {
                out.insert(key.to_string(), value.clone());
            }
        }
        Value::Object(out)
    }

    /// The list as the page sends it: the stored clients, changed or left out. A client is made by its own door, which gives it its id
    /// and its key (`POST /api/consumers/create`): an id the list brings that no stored client has is refused.
    fn write_routes(&self, routes: &Value, routers: Option<Value>) -> Result<Value, AppError> {
        let current = self.load()?;
        let stored = current.get("routes").and_then(Value::as_array).map_or(&[][..], Vec::as_slice);
        let by_id: BTreeMap<String, &Value> = stored.iter().map(|route| (ClientIds::of(route), route)).collect();
        let (mut cleaned, mut seen) = (Vec::new(), BTreeSet::new());
        for route in routes.as_array().map_or(&[][..], Vec::as_slice) {
            let row = RouterDsl::route(&Self::kept(route, &by_id))?;
            let id = ClientIds::of(&row);
            if !by_id.contains_key(&id) {
                return Err(AppError::new(format!(
                    "no client has the id {id}: a client is made with ＋ in the Clients column (POST /api/consumers/create)"
                )));
            }
            if !seen.insert(id.clone()) {
                return Err(AppError::new(format!("the list names the client {id} twice")));
            }
            cleaned.push(row);
        }
        KeyAudit::enforce(&cleaned)?;
        let source = routers.or_else(|| current.get("routers").cloned());
        let routers = Self::normalize_routers(source.as_ref(), Some(&mut cleaned))?;
        let policy = current
            .get("policy")
            .filter(|policy| Coerce::truthy(Some(*policy)))
            .cloned()
            .unwrap_or_else(|| RouterDsl::policy(None));
        let mut payload = json!({"routes": cleaned, "policy": policy, "routers": routers, "stopRequests": current.get("stopRequests"), "entry": current.get("entry")});
        Self::keep_former_ports(&mut payload, &current);
        self.write_payload(payload.clone())?;
        Ok(payload)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_version_is_of_the_stored_list() {
        let one = ProxyRevisions::of(&json!({"routes": [{"b": 1, "a": "ю"}], "routers": null}));
        let same = ProxyRevisions::of(&json!({"routes": [{"a": "ю", "b": 1}]}));
        assert_eq!(one, same);
        assert_ne!(one, ProxyRevisions::of(&json!({"routes": []})));
        assert_eq!(one.get("routes").unwrap().as_str().unwrap().len(), 16);
    }

    #[test]
    fn cables_of_a_port_nobody_has_go() {
        let inputs = PortInputs::new(&[json!({"id": "client-1", "routerId": "r"})]);
        let router = json!({"graph": {"edges": [{"from": "in:client-1", "to": "out:x"}, {"from": "in:client-2", "to": "out:x"}, {"from": "rule:a", "to": "out:x"}], "inputs": {"client-1": {}, "client-2": {}}}});
        let cut = inputs.forget_absent(&router);
        assert_eq!(cut.get("graph").unwrap().get("edges").unwrap().as_array().unwrap().len(), 2);
        assert_eq!(cut.get("graph").unwrap().get("inputs"), Some(&json!({"client-1": {}})));
        assert_eq!(inputs.of_router("r"), ["client-1"]);
    }

    #[test]
    fn keys_the_entry_cannot_tell_apart_are_refused() {
        let words = KeyAudit::enforce(&[json!({"apiKey": "abcdef", "label": "b"}), json!({"apiKey": "abcdef", "label": "a"})])
            .unwrap_err()
            .message;
        assert_eq!(words, "clients a, b share one key (…cdef) — the entry could not tell them apart; give each its own");
        assert_eq!(
            KeyAudit::enforce(&[json!({"label": "c"})]).unwrap_err().message,
            "client c has no key — it would have no way in; give it a key first"
        );
        assert!(KeyAudit::enforce(&[json!({"apiKey": "k", "label": "a"})]).is_ok());
    }
}
