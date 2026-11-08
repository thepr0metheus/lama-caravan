//! The board's side of the entry for keys: where a consumer calls the caravan, and the entry's own settings.

use super::config::ProxiesConfig;
use crate::app::App;
use crate::common::entry::{BuiltinClient, EntryDoor};
use crate::common::misc::ProxyHeartbeat;
use crate::domain::client_proxy::ProxyRoute;
use rules::{AppError, Coerce, PyRepr};
use serde_json::{Value, json};

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

/// Where a consumer calls the caravan: one rule for the board's client rows, the agents' cards and Routing's clients panel.
pub struct ConsumerAddress {
    host: String,
    door: Option<bool>,
    entry_port: i64,
    public: String,
    entry_url: String,
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
        Self { host: host.to_string(), door, entry_port, public, entry_url }
    }

    /// Where every client calls: the entry; "" while it is off.
    pub fn client(&self) -> String {
        self.entry_url.clone()
    }

    /// The address of an agent's port of the older kind, as its record was bound: nothing when no machine reaches the ports.
    pub fn of(&self, port: i64) -> String {
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
        Ok(())
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
            let mut taken = config.all_taken_ports();
            taken.remove(&current);
            if taken.contains(&port) {
                return Err(AppError::with_status(
                    format!("port {port} is already the fleet's (a cell or an excluded port)"),
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
    fn every_client_is_reached_through_the_entry() {
        let config = json!({"entry": {"port": 9, "publicUrl": "https://pub"}, "routes": [{"id": "c1"}]});
        let address = ConsumerAddress::new(&config, "h", Some(true));
        assert_eq!(address.client(), "https://pub");
        assert_eq!(address.entry()["url"], "https://pub");
        assert_eq!(ConsumerAddress::new(&json!({"entry": {"port": 9}}), "h", Some(true)).client(), "http://h:9/v1");
        let shut = ConsumerAddress::new(&json!({"entry": {"port": 9}}), "h", Some(false));
        assert_eq!((shut.client(), shut.of(2)), (String::new(), String::new()));
        assert_eq!(ConsumerAddress::new(&json!({}), "h", Some(true)).client(), "");
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
    }
}
