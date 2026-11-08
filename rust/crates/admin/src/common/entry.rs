//! What the controller says of a client of the entry beside what the proxy's half reads: the entry's door, a key as it may be shown, the clients the caravan makes itself, and what a client is closed to, as a route keeps it.

use rules::{AppError, ClientDeny, Coerce};
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;

/// The one door the consumers share.
pub struct EntryDoor;

impl EntryDoor {
    /// Where it opens when nobody said.
    pub const DEFAULT_PORT: i64 = 23999;
    const PORT_MIN: i64 = 1024;
    const PORT_MAX: i64 = 65535;
    const URL_MOST: usize = 200;

    /// `^https?://[A-Za-z0-9.\-]+(:\d{1,5})?(/[\w\-./]*)?$`.
    fn is_public_url(url: &str) -> bool {
        let Some(rest) = url.strip_prefix("https://").or_else(|| url.strip_prefix("http://")) else {
            return false;
        };
        let (place, path) = rest.find('/').map_or((rest, ""), |at| rest.split_at(at));
        let (host, port) = place.split_once(':').unwrap_or((place, ""));
        let host_ok =
            !host.is_empty() && host.chars().all(|letter| letter.is_ascii_alphanumeric() || matches!(letter, '.' | '-'));
        let port_ok =
            !place.contains(':') || ((1..=5).contains(&port.len()) && port.chars().all(|letter| letter.is_ascii_digit()));
        let path_ok = path.chars().all(|letter| letter.is_alphanumeric() || matches!(letter, '_' | '-' | '.' | '/'));
        host_ok && port_ok && path_ok
    }

    /// The entry as the config keeps it; empty for one that is off.
    pub fn clean(raw: Option<&Value>) -> Value {
        let Some(raw) = raw.filter(|raw| raw.is_object()) else {
            return json!({});
        };
        // absent-ok: `int(raw.get("port") or 0)`: no port is out of the range below, and the entry is off.
        let port = Coerce::whole(raw.get("port"));
        if !(Self::PORT_MIN..=Self::PORT_MAX).contains(&port) {
            return json!({});
        }
        let said = Coerce::stripped(raw.get("publicUrl"));
        let url = Coerce::first_letters(&said, Self::URL_MOST);
        if Self::is_public_url(url) { json!({"port": port, "publicUrl": url}) } else { json!({"port": port}) }
    }

    /// What anything outside the controller is shown of a key.
    pub fn tail(key: &str) -> String {
        let count = key.chars().count();
        key.chars().skip(count.saturating_sub(4)).collect()
    }

    /// A route as it may leave the controller.
    pub fn public_route(route: &Value) -> Value {
        let mut out = Coerce::fields(route);
        out.shift_remove("apiKey");
        out.insert("keyTail".to_string(), json!(Self::tail(&Coerce::text(route.get("apiKey")))));
        Value::Object(out)
    }

    /// `{key: names}` of the keys more than one client carries, the names in order.
    pub fn shared_keys(routes: &[Value]) -> BTreeMap<String, Vec<String>> {
        let mut names: BTreeMap<String, Vec<String>> = BTreeMap::new();
        for route in routes {
            let key = Coerce::stripped(route.get("apiKey"));
            if !key.is_empty() {
                names.entry(key).or_default().push(Coerce::text(route.get("label")));
            }
        }
        names.retain(|_, found| found.len() > 1);
        for found in names.values_mut() {
            found.sort_unstable();
        }
        names
    }
}

/// The clients the caravan makes itself.
pub struct BuiltinClient;

impl BuiltinClient {
    /// The route's field.
    pub const FIELD: &'static str = "builtin";
    /// Open WebUI.
    pub const OPEN_WEBUI: &'static str = "open-webui";
    /// opencode.
    pub const OPENCODE: &'static str = "opencode";
    /// Every kind: its name, whether it holds a config of its own, whether it may have more than one client.
    pub const KINDS: [(&'static str, &'static str, bool, bool); 2] =
        [(Self::OPEN_WEBUI, "Open WebUI", false, false), (Self::OPENCODE, "opencode", true, true)];

    fn clean(raw: Option<&Value>) -> Option<&str> {
        raw.and_then(Value::as_str).filter(|said| Self::KINDS.iter().any(|(kind, ..)| kind == said))
    }

    /// The field as both normalizers keep it.
    pub fn fields(route: &Value) -> Map<String, Value> {
        let mut out = Map::new();
        if let Some(said) = Self::clean(route.get(Self::FIELD)) {
            out.insert(Self::FIELD.to_string(), json!(said));
        }
        out
    }

    /// The kind of built-in client `route` is; "" for none.
    pub fn kind(route: &Value) -> &str {
        if route.get("kind").and_then(Value::as_str) != Some("consumer") {
            return "";
        }
        // absent-ok: a route of no built-in kind has none.
        Self::clean(route.get(Self::FIELD)).unwrap_or_default()
    }

    /// The name a kind is made with.
    pub fn name(kind: &str) -> &'static str {
        Self::KINDS.iter().find(|(said, ..)| *said == kind).map_or("", |row| row.1)
    }

    /// Whether a kind holds a config the board writes out.
    pub fn has_config(kind: &str) -> bool {
        Self::KINDS.iter().any(|row| row.0 == kind && row.2)
    }

    /// Whether a kind may have more than one client.
    pub fn many(kind: &str) -> bool {
        Self::KINDS.iter().any(|row| row.0 == kind && row.3)
    }

    /// The built-in client of `kind` among `routes`.
    pub fn find<'routes>(routes: &'routes [Value], kind: &str) -> Option<&'routes Value> {
        routes.iter().find(|route| Self::kind(route) == kind)
    }

    /// A write of the routes refused when it would take a kind's last client.
    pub fn audit(before: &[Value], after: &[Value]) -> Result<(), AppError> {
        for (kind, name, ..) in Self::KINDS {
            if Self::find(after, kind).is_none() && Self::find(before, kind).is_some() {
                return Err(AppError::with_status(
                    format!("{name} is built into the caravan and its last client stays: it cannot be deleted"),
                    409,
                ));
            }
        }
        Ok(())
    }
}

/// A client's own fields as both normalizers keep them.
pub struct ClientFields;

impl ClientFields {
    const DENY_KINDS: [&'static str; 4] = ["pool", "model", "account", "host"];
    const DENY_MOST: usize = 200;
    const DENY_KEY_MOST: usize = 200;

    /// What a client is closed to, as its route keeps it: in the operator's order, each key once.
    pub fn deny_list(raw: Option<&Value>) -> Vec<String> {
        let mut out: Vec<String> = Vec::new();
        for item in raw.and_then(Value::as_array).into_iter().flatten() {
            let key = item.as_str().map_or("", Coerce::strip);
            let known = key.split_once(':').is_some_and(|(kind, rest)| Self::DENY_KINDS.contains(&kind) && !rest.is_empty());
            if known && key.chars().count() <= Self::DENY_KEY_MOST && !out.iter().any(|said| said == key) {
                out.push(key.to_string());
            }
        }
        out.truncate(Self::DENY_MOST);
        out
    }

    /// `deny`, and `builtin` when it is one.
    pub fn of(route: &Value) -> Map<String, Value> {
        let mut out = Map::new();
        out.insert(ClientDeny::FIELD.to_string(), json!(Self::deny_list(route.get(ClientDeny::FIELD))));
        out.extend(BuiltinClient::fields(route));
        out
    }
}

/// `ClientName`'s acceptance and reading of a policy's word.
pub struct ClientNameWord;

impl ClientNameWord {
    /// The policy's key.
    pub const KEY: &'static str = "clientName";
    /// The longest a name may be.
    pub const LONGEST: usize = 120;

    /// Whether `raw` can be a name: printable Latin, of a sane length.
    pub fn acceptable(raw: Option<&Value>) -> bool {
        raw.and_then(Value::as_str).is_some_and(|text| {
            let text = Coerce::strip(text);
            text.chars().count() <= Self::LONGEST && text.chars().all(|letter| (' '..='~').contains(&letter))
        })
    }

    /// The name a policy holds; "" for none.
    pub fn of(policy: Option<&Value>) -> String {
        let raw = policy.and_then(|policy| policy.get(Self::KEY));
        if Self::acceptable(raw) { Coerce::stripped(raw) } else { String::new() }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_door_keeps_only_what_it_can_be() {
        assert_eq!(
            EntryDoor::clean(Some(&json!({"port": 23999, "publicUrl": "https://a.b:1/c"}))),
            json!({"port": 23999, "publicUrl": "https://a.b:1/c"})
        );
        assert_eq!(EntryDoor::clean(Some(&json!({"port": "23999", "publicUrl": "ftp://x"}))), json!({"port": 23999}));
        assert_eq!(EntryDoor::clean(Some(&json!({"port": 80}))), json!({}));
        assert_eq!(EntryDoor::clean(None), json!({}));
    }

    #[test]
    fn a_key_is_shown_by_its_tail() {
        assert_eq!(EntryDoor::public_route(&json!({"id": "c1", "apiKey": "abcdefg"})), json!({"id": "c1", "keyTail": "defg"}));
        assert_eq!(EntryDoor::public_route(&json!({"id": "c1"})), json!({"id": "c1", "keyTail": ""}));
        let routes =
            [json!({"apiKey": "k", "label": "b"}), json!({"apiKey": "k", "label": "a"}), json!({"apiKey": "z", "label": "c"})];
        assert_eq!(EntryDoor::shared_keys(&routes).get("k"), Some(&vec!["a".to_string(), "b".to_string()]));
        assert_eq!(EntryDoor::shared_keys(&routes).len(), 1);
    }

    #[test]
    fn a_built_in_client_stays() {
        let client = json!({"kind": "consumer", "builtin": "open-webui"});
        assert_eq!(BuiltinClient::kind(&client), "open-webui");
        assert_eq!(BuiltinClient::kind(&json!({"builtin": "open-webui"})), "");
        assert_eq!(BuiltinClient::audit(std::slice::from_ref(&client), &[]).unwrap_err().status, 409);
        assert!(BuiltinClient::audit(std::slice::from_ref(&client), std::slice::from_ref(&client)).is_ok());
    }

    #[test]
    fn a_name_is_printable_latin() {
        assert!(ClientNameWord::acceptable(Some(&json!(" pi (linux) "))));
        assert!(!ClientNameWord::acceptable(Some(&json!("имя"))));
        assert!(!ClientNameWord::acceptable(Some(&json!(5))));
        assert_eq!(ClientNameWord::of(Some(&json!({"clientName": " pi "}))), "pi");
        assert_eq!(ClientNameWord::of(None), "");
    }
}
