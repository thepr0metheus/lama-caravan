//! What refuses a save of the proxy's settings: a stale copy, a key two clients share, a cable that names nothing.

use super::*;

/// A save made from an older version of a list than the stored one: refused, nothing is overwritten.
pub struct StaleCopy;

impl StaleCopy {
    pub(super) const WORDS: &'static str =
        "changed since this page read them: nothing was saved — the page makes its change again on the current version";

    /// The refusal.
    pub fn refusal(name: &str) -> AppError {
        AppError::with_status(format!("the {name} {}", Self::WORDS), 409)
    }

    /// Whether a refusal is this one: the page takes the board it should have read.
    pub fn is(refusal: &AppError) -> bool {
        refusal.status == 409 && refusal.message.contains(Self::WORDS)
    }
}

/// Which version of the proxy document a page was shown, list by list.
pub struct ProxyRevisions;

impl ProxyRevisions {
    pub(super) const LISTS: [&'static str; 2] = ["routes", "routers"];

    pub(super) fn sorted(value: &Value) -> Value {
        match value {
            Value::Object(fields) => {
                let mut keys: Vec<&String> = fields.keys().collect();
                keys.sort();
                let out: Map<String, Value> =
                    keys.into_iter().filter_map(|key| fields.get(key).map(|item| (key.clone(), Self::sorted(item)))).collect();
                Value::Object(out)
            }
            Value::Array(items) => Value::Array(items.iter().map(Self::sorted).collect()),
            other => other.clone(),
        }
    }

    /// `json.dumps(value, sort_keys=True, …)`'s digest, the first of it.
    pub(super) fn digest(value: Option<&Value>) -> String {
        let text = PythonJson::compact_letters(&Self::sorted(value.unwrap_or(&Value::Null)));
        Coerce::first_letters(&Sha256::of(text.as_bytes()), 16).to_string()
    }

    /// The version of each list in a reading of the document, as stored.
    pub fn of(payload: &Value) -> Value {
        let lists: Map<String, Value> =
            Self::LISTS.iter().map(|name| ((*name).to_string(), json!(Self::digest(payload.get(*name))))).collect();
        Value::Object(lists)
    }
}

/// The clients a graph may start from: an input is `in:<client id>`, the id the board knows the client by (2026-11-07).
pub struct PortInputs {
    pub(super) routes: Vec<Value>,
    pub(super) known: BTreeSet<String>,
}

impl PortInputs {
    pub(super) fn of_route(route: &Value) -> String {
        ClientIds::of(route)
    }

    /// The inputs of these routes.
    pub fn new(routes: &[Value]) -> Self {
        let routes: Vec<Value> = routes.iter().filter(|route| route.is_object()).cloned().collect();
        let known = routes.iter().map(Self::of_route).collect();
        Self { routes, known }
    }

    /// The inputs of one router.
    pub(super) fn of_router(&self, router_id: &str) -> Vec<String> {
        self.routes
            .iter()
            .filter(|route| route.get("routerId").and_then(Value::as_str) == Some(router_id))
            .map(Self::of_route)
            .collect()
    }

    pub(super) fn holds(&self, reference: Option<&Value>) -> bool {
        let reference = Coerce::text(reference);
        reference.strip_prefix("in:").is_none_or(|port| self.known.contains(port))
    }

    /// `router` without the cables and wait budgets of ports no route has: a copy.
    pub(super) fn forget_absent(&self, router: &Value) -> Value {
        let Some(graph) = router.get("graph").filter(|graph| graph.is_object()) else {
            return router.clone();
        };
        let mut kept = Coerce::fields(graph);
        if let Some(edges) = graph.get("edges").and_then(Value::as_array) {
            let edges: Vec<Value> = edges
                .iter()
                .filter(|edge| !edge.is_object() || (self.holds(edge.get("from")) && self.holds(edge.get("to"))))
                .cloned()
                .collect();
            kept.insert("edges".to_string(), Value::Array(edges));
        }
        if let Some(inputs) = graph.get("inputs").and_then(Value::as_object) {
            let inputs: Map<String, Value> = inputs
                .iter()
                .filter(|(port, _)| self.known.contains(*port))
                .map(|(port, config)| (port.clone(), config.clone()))
                .collect();
            kept.insert("inputs".to_string(), Value::Object(inputs));
        }
        let mut out = Coerce::fields(router);
        out.insert("graph".to_string(), Value::Object(kept));
        Value::Object(out)
    }
}

/// The keys of the routes, as the entry needs them.
pub struct KeyAudit;

impl KeyAudit {
    /// Refuses clients the entry could not tell apart, and a client with no key: the entry is its only way in.
    pub fn enforce(routes: &[Value]) -> Result<(), AppError> {
        let routes: Vec<Value> = routes.iter().filter(|route| route.is_object()).cloned().collect();
        let mut found: Vec<String> = Vec::new();
        for (key, names) in EntryDoor::shared_keys(&routes) {
            found.push(format!(
                "clients {} share one key (…{}) — the entry could not tell them apart; give each its own",
                names.join(", "),
                EntryDoor::tail(&key)
            ));
        }
        for route in &routes {
            if Coerce::stripped(route.get("apiKey")).is_empty() {
                found.push(format!(
                    "client {} has no key — it would have no way in; give it a key first",
                    Coerce::text(route.get("label"))
                ));
            }
        }
        if found.is_empty() { Ok(()) } else { Err(AppError::new(found.join("; "))) }
    }
}
