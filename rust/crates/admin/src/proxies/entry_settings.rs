//! The board's side of the entry for keys: where a consumer calls the caravan, and the entry's own settings.

use super::config::ProxiesConfig;
use crate::app::App;
use crate::common::entry::{BuiltinClient, EntryDoor};
use crate::common::misc::ProxyHeartbeat;
use crate::domain::client_proxy::ProxyRoute;
use rules::{AppError, Coerce, PyRepr};
use serde_json::{Value, json};
use std::collections::BTreeSet;

/// Whether other machines reach the caravan's ports, on the proxy's own word.
pub struct PortDoor;

impl PortDoor {
    /// `Some(true)` for a listen address other machines can reach, `Some(false)` for a loopback one, `None` for no address.
    pub fn opens(host: Option<&Value>) -> Option<bool> {
        let host = Coerce::stripped(host).to_lowercase();
        if host.is_empty() {
            return None;
        }
        Some(!(host == "localhost" || host == "::1" || host.starts_with("127.")))
    }

    /// What the proxy says now; `None` when it says nothing, or stopped saying it.
    pub fn open(app: &App) -> Option<bool> {
        let raw = std::fs::read(&app.paths.agent_proxy_state_file).ok()?;
        let payload: Value = serde_json::from_slice(&raw).ok()?;
        if !payload.is_object() || !ProxyHeartbeat::fresh(payload.get("time"), app.now()) {
            return None;
        }
        Self::opens(payload.get("listenHost"))
    }
}

/// Where a consumer calls the caravan: one rule for the board's proxy rows, the agents' cards and Routing's clients panel.
pub struct ConsumerAddress {
    host: String,
    door: Option<bool>,
    entry_port: i64,
    public: String,
    entry_url: String,
    closed: BTreeSet<i64>,
}

impl ConsumerAddress {
    fn port_of(raw: Option<&Value>) -> i64 {
        // absent-ok: `int(... or 0)`: a port not named is none.
        Coerce::whole(raw)
    }

    /// The reading of `config` from `host`, with the proxy's word on whether its ports are reachable.
    pub fn new(config: &Value, host: &str, door: Option<bool>) -> Self {
        let entry = config.get("entry");
        let entry_port = Self::port_of(entry.and_then(|entry| entry.get("port")));
        let public =
            if entry_port != 0 { Coerce::stripped(entry.and_then(|entry| entry.get("publicUrl"))) } else { String::new() };
        let own = if door == Some(false) { String::new() } else { ProxyRoute::port_url(host, entry_port) };
        let entry_url = if entry_port == 0 {
            String::new()
        } else if public.is_empty() {
            own
        } else {
            public.clone()
        };
        let closed = config
            .get("routes")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter(|route| route.is_object() && Coerce::truthy(route.get("portClosed")))
            .map(|route| Self::port_of(route.get("port")))
            .collect();
        Self { host: host.to_string(), door, entry_port, public, entry_url, closed }
    }

    /// The address of `port`: the entry for a closed one, nothing when no machine reaches the ports.
    pub fn of(&self, port: i64) -> String {
        if self.closed.contains(&port) && !self.entry_url.is_empty() {
            return self.entry_url.clone();
        }
        if self.door == Some(false) {
            return String::new();
        }
        ProxyRoute::port_url(&self.host, port)
    }

    /// The entry as the board shows it.
    pub fn entry(&self) -> Value {
        json!({"url": self.entry_url, "port": if self.entry_port != 0 { json!(self.entry_port) } else { Value::Null }, "publicUrl": self.public})
    }
}

/// The entry's port and public address, as the board sets them.
pub struct EntrySettings<'app> {
    app: &'app App,
}

impl<'app> EntrySettings<'app> {
    const PORT_MIN: i64 = 1024;
    const PORT_MAX: i64 = 65535;

    /// The settings of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// Whether `url` can be the entry's public address.
    fn is_public_url(url: &str) -> bool {
        let rest = url.strip_prefix("https://").or_else(|| url.strip_prefix("http://"));
        let Some(rest) = rest else {
            return false;
        };
        let (place, path) = rest.split_once('/').map_or((rest, ""), |(place, path)| (place, path));
        let (host, port) = place.split_once(':').map_or((place, None), |(host, port)| (host, Some(port)));
        let host_good =
            !host.is_empty() && host.chars().all(|letter| letter.is_ascii_alphanumeric() || matches!(letter, '.' | '-'));
        let port_good = port.is_none_or(|port| (1..=5).contains(&port.len()) && port.chars().all(|digit| digit.is_ascii_digit()));
        let path_good = path.chars().all(|letter| letter.is_alphanumeric() || matches!(letter, '_' | '-' | '.' | '/'));
        host_good && port_good && path_good
    }

    fn ports_of(routes: &[Value]) -> Vec<i64> {
        let mut closed: Vec<i64> = routes
            .iter()
            .filter(|route| Coerce::truthy(route.get("portClosed")))
            .map(|route| ConsumerAddress::port_of(route.get("port")))
            .collect();
        closed.sort_unstable();
        closed
    }

    /// The settings as the board reads them.
    pub fn read(&self) -> Result<Value, AppError> {
        let config = ProxiesConfig::of(self.app).load()?;
        let entry = config.get("entry");
        let port = ConsumerAddress::port_of(entry.and_then(|entry| entry.get("port")));
        let routes = Coerce::list(config.get("routes"));
        Ok(json!({
            "ok": true,
            "port": if port != 0 { json!(port) } else { Value::Null },
            "publicUrl": entry.and_then(|entry| entry.get("publicUrl")).filter(|said| Coerce::truthy(Some(*said))).cloned().unwrap_or_else(|| json!("")),
            "listening": port != 0 && ProxiesConfig::port_is_listening(port),
            "keyedRoutes": routes.iter().filter(|route| !Coerce::stripped(route.get("apiKey")).is_empty()).count(),
            "closedPorts": Self::ports_of(&routes),
        }))
    }

    /// What keeps the entry from going off: a client's only way in is the entry.
    fn refuse_off(routes: &[Value]) -> Result<(), AppError> {
        if let Some(builtin) = routes.iter().find(|route| !BuiltinClient::kind(route).is_empty()) {
            let label = Coerce::text(builtin.get("label"));
            let shown = if label.is_empty() { BuiltinClient::name(BuiltinClient::kind(builtin)).to_string() } else { label };
            return Err(AppError::with_status(
                format!("{shown} is built into the caravan and calls it only through the entry: the entry stays on"),
                409,
            ));
        }
        let clients: Vec<String> = routes
            .iter()
            .filter(|route| route.get("kind").and_then(Value::as_str) == Some("consumer"))
            .map(|route| Coerce::str_of(route.get("label")))
            .collect();
        if let [only] = clients.as_slice() {
            return Err(AppError::with_status(
                format!("client {only} calls the caravan only through the entry: delete it before turning the entry off"),
                409,
            ));
        }
        if !clients.is_empty() {
            return Err(AppError::with_status(
                format!(
                    "clients {} call the caravan only through the entry: delete them before turning the entry off",
                    clients.join(", ")
                ),
                409,
            ));
        }
        let closed = Self::ports_of(routes);
        let named: Vec<String> = closed.iter().map(ToString::to_string).collect();
        let named = named.join(", ");
        match closed.len() {
            0 => Ok(()),
            1 => Err(AppError::with_status(
                format!("port {named} is closed — its agent comes in only through the entry; open it before closing the entry"),
                409,
            )),
            _ => Err(AppError::with_status(
                format!(
                    "ports {named} are closed — their agents come in only through the entry; open them before closing the entry"
                ),
                409,
            )),
        }
    }

    /// The settings from now on.
    pub fn write(&self, body: &Value) -> Result<Value, AppError> {
        let raw = body.get("port").filter(|raw| !raw.is_null() && **raw != json!(""));
        let port = match raw {
            None => 0,
            Some(raw) => {
                Coerce::int(raw).ok_or_else(|| AppError::new(format!("port must be a number, got {}", PyRepr::of_value(raw))))?
            }
        };
        let url = Coerce::stripped(body.get("publicUrl"));
        if !url.is_empty() && !Self::is_public_url(&url) {
            return Err(AppError::new(format!("publicUrl must be an http(s) address, got {}", PyRepr::of(&url))));
        }
        let config = ProxiesConfig::of(self.app);
        let loaded = config.load()?;
        let current = ConsumerAddress::port_of(loaded.get("entry").and_then(|entry| entry.get("port")));
        let routes: Vec<Value> = loaded
            .get("routes")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter(|route| route.is_object())
            .cloned()
            .collect();
        if port == 0 {
            Self::refuse_off(&routes)?;
        } else {
            if !(Self::PORT_MIN..=Self::PORT_MAX).contains(&port) {
                return Err(AppError::new(format!("the entry's port must be {}..{}", Self::PORT_MIN, Self::PORT_MAX)));
            }
            let mut taken = config.all_taken_ports(&routes);
            taken.remove(&current);
            if taken.contains(&port) {
                return Err(AppError::with_status(
                    format!("port {port} is already the fleet's (a route, a cell or an excluded port)"),
                    409,
                ));
            }
            if port != current && ProxiesConfig::port_is_listening(port) {
                return Err(AppError::with_status(format!("something already listens on port {port}"), 409));
            }
        }
        let mut payload = config.read_payload();
        let entry = if port != 0 { EntryDoor::clean(Some(&json!({"port": port, "publicUrl": url}))) } else { json!({}) };
        Coerce::put(&mut payload, "entry", entry);
        config.write_payload(payload)?;
        self.read()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_door_is_open_unless_it_listens_at_home() {
        assert_eq!(PortDoor::opens(Some(&json!("0.0.0.0"))), Some(true));
        assert_eq!(PortDoor::opens(Some(&json!("127.0.0.1"))), Some(false));
        assert_eq!(PortDoor::opens(Some(&json!("LOCALHOST"))), Some(false));
        assert_eq!(PortDoor::opens(Some(&json!("::1"))), Some(false));
        assert_eq!(PortDoor::opens(None), None);
    }

    #[test]
    fn a_closed_port_is_reached_through_the_entry() {
        let config =
            json!({"entry": {"port": 9, "publicUrl": "https://pub"}, "routes": [{"port": 1, "portClosed": true}, {"port": 2}]});
        let address = ConsumerAddress::new(&config, "h", Some(true));
        assert_eq!(address.of(1), "https://pub");
        assert!(address.of(2).contains('2'));
        assert_eq!(address.entry()["url"], "https://pub");
        let shut =
            ConsumerAddress::new(&json!({"entry": {"port": 9}, "routes": [{"port": 1, "portClosed": true}]}), "h", Some(false));
        assert_eq!(shut.of(1), "");
        assert_eq!(shut.of(2), "");
    }

    #[test]
    fn a_public_address_is_an_http_one() {
        for good in ["https://a.b", "http://a-b.c:8080/x/y_z", "https://a.b/"] {
            assert!(EntrySettings::is_public_url(good), "{good}");
        }
        for bad in ["ftp://a", "https://", "https://a b", "https://a:123456", "a.b"] {
            assert!(!EntrySettings::is_public_url(bad), "{bad}");
        }
    }

    #[test]
    fn the_entry_stays_on_while_something_comes_through_it() {
        let status = |routes: Value| EntrySettings::refuse_off(routes.as_array().unwrap()).map_err(|error| error.message);
        assert!(status(json!([{"kind": "other", "port": 1}])).is_ok());
        assert!(
            status(json!([{"kind": "consumer", "builtin": "open-webui", "label": "W"}])).unwrap_err().starts_with("W is built")
        );
        assert!(status(json!([{"kind": "consumer", "label": "a"}])).unwrap_err().starts_with("client a calls"));
        assert!(
            status(json!([{"kind": "consumer", "label": "a"}, {"kind": "consumer", "label": "b"}]))
                .unwrap_err()
                .starts_with("clients a, b call")
        );
        assert!(status(json!([{"port": 1, "portClosed": true}])).unwrap_err().starts_with("port 1 is closed"));
    }
}
