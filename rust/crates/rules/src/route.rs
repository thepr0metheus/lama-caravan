//! A route as the proxy reads it.

use crate::client_deny::ClientDeny;
use crate::coerce::Coerce;
use serde_json::Value;

/// A client's route, cleaned. What is here is what the proxy goes by; the file keeps the rest.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Route {
    /// The name on the board and in the journal.
    pub label: String,
    /// The route's port: its name in the state's `agents`, even when closed.
    pub port: i64,
    /// `consumer` for a client of the entry.
    pub kind: String,
    /// What the client is closed to.
    pub deny: ClientDeny,
    /// The address the file names; a consumer's request goes where its model stands.
    pub upstream_host: String,
    /// The port the file names.
    pub upstream_port: i64,
    /// Whether the route is switched on.
    pub enabled: bool,
    /// `open`, `paused` or `drain`.
    pub mode: String,
    /// The client's key; empty for an open port.
    pub api_key: String,
    /// Whether its own port is closed, so that it is reached through the entry by its key.
    pub port_closed: bool,
    /// Above 0 its requests may push others out.
    pub priority: i64,
    /// Seconds its client waits for a whole answer; 0 when it says none.
    pub client_timeout_seconds: i64,
    /// The window the operator set for this one client; `None`: not set.
    pub context_limit: Option<i64>,
    /// The operator's opt-in to publish the model's own size even above that limit.
    pub context_auto: bool,
}

impl Route {
    /// The address and the port a route takes when it names none: `UPSTREAM_HOST` and `UPSTREAM_PORT`.
    const DEFAULT_HOST: &'static str = "127.0.0.1";
    const DEFAULT_PORT: i64 = 8080;
    /// The fields that must read as a whole number: a broken one drops the route.
    const PERCENTS: [&'static str; 3] = ["cloudFallbackPct", "priorityPreemptPct", "queueAbortPct"];

    /// The route `raw` says, or `None` for one that does not read: every reader then skips it.
    pub fn normalize(raw: &Value) -> Option<Self> {
        let fields = raw.as_object()?;
        let port = Coerce::int(fields.get("port")?)?;
        let host = Coerce::stripped(Some(raw.get("upstreamHost").filter(|v| Coerce::truthy(Some(*v))).unwrap_or(&Value::Null)));
        let upstream_port = match fields.get("upstreamPort").filter(|value| Coerce::truthy(Some(*value))) {
            Some(value) => Coerce::int(value)?,
            None => Self::DEFAULT_PORT,
        };
        let kind = Coerce::stripped(fields.get("kind")).to_lowercase();
        if kind == "service" {
            return None;
        }
        let priority = Coerce::int_or_zero(fields.get("priority"))?;
        let client_timeout_seconds = Coerce::int_or_zero(fields.get("clientTimeoutSeconds"))?.max(0);
        let context_limit = Self::context_limit(fields.get("contextLength"))?;
        for percent in Self::PERCENTS {
            if let Some(value) = fields.get(percent).filter(|value| !value.is_null()) {
                Coerce::int(value)?;
            }
        }
        Some(Self {
            label: Self::label(fields.get("label"), port),
            port,
            deny: if kind == "consumer" { ClientDeny::clean(fields.get(ClientDeny::FIELD)) } else { ClientDeny::default() },
            kind,
            upstream_host: if host.is_empty() { Self::DEFAULT_HOST.to_string() } else { host },
            upstream_port,
            enabled: fields.get("enabled").is_none_or(|value| Coerce::truthy(Some(value))),
            mode: Self::mode(fields.get("mode")),
            api_key: Coerce::stripped(fields.get("apiKey")),
            port_closed: Coerce::truthy(fields.get("portClosed")),
            priority,
            client_timeout_seconds,
            context_limit,
            context_auto: Coerce::truthy(fields.get("contextAuto")),
        })
    }

    /// The route's limit: digits above zero, any other text being no limit. `None` for digits that do not read as a number, and for
    /// digits other than ASCII's: the route is then dropped.
    fn context_limit(raw: Option<&Value>) -> Option<Option<i64>> {
        let said = Coerce::text(raw);
        let digits = Coerce::strip(&said).trim_start_matches('-');
        if digits.is_empty() || !digits.chars().all(char::is_numeric) {
            return Some(None);
        }
        if !digits.is_ascii() {
            return None;
        }
        let number = Coerce::int(&Value::String(said.clone()))?;
        Some(Some(number).filter(|limit| *limit > 0))
    }

    fn label(raw: Option<&Value>, port: i64) -> String {
        let fallback = format!("port-{port}");
        let said = Coerce::text(raw);
        let said = if said.is_empty() { fallback.clone() } else { said };
        let cut = Coerce::first_letters(Coerce::strip(&said), 80).to_string();
        if cut.is_empty() { fallback } else { cut }
    }

    fn mode(raw: Option<&Value>) -> String {
        let said = Coerce::stripped(raw).to_lowercase();
        if said.is_empty() { "open".to_string() } else { said }
    }

    /// Whether it is a client of the entry.
    pub fn is_consumer(&self) -> bool {
        self.kind == "consumer"
    }

    /// Whether its requests are held back on the board.
    pub fn is_paused(&self) -> bool {
        self.mode == "paused" || self.mode == "drain"
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn route(raw: Value) -> Route {
        Route::normalize(&raw).unwrap()
    }

    #[test]
    fn only_a_consumer_is_one() {
        assert!(route(json!({"port": 1, "kind": "consumer"})).is_consumer());
        assert!(!route(json!({"port": 1, "kind": "agent"})).is_consumer());
        assert!(!route(json!({"port": 1})).is_consumer());
    }

    #[test]
    fn held_back_is_paused_or_draining_and_nothing_else() {
        assert!(route(json!({"port": 1, "mode": "paused"})).is_paused());
        assert!(route(json!({"port": 1, "mode": "drain"})).is_paused());
        assert!(!route(json!({"port": 1, "mode": "open"})).is_paused());
        assert!(!route(json!({"port": 1})).is_paused());
    }
}
