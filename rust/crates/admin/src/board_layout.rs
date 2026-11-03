//! The order of the board's cards.

use crate::app::App;
use crate::store::admin::AdminStore;
use rules::{AppError, Coerce, PyRepr};
use serde_json::{Map, Value, json};

/// The stored order of the server cards, and the one way to change it.
pub struct ServerOrder;

impl ServerOrder {
    const KINDS: [&'static str; 2] = ["node", "cloud"];
    const LIMIT: usize = 500;
    const KEY_LIMIT: usize = 200;

    fn is_key(value: &Value) -> bool {
        let Some(word) = value.as_str() else {
            return false;
        };
        if word.is_empty() || word.chars().count() > Self::KEY_LIMIT {
            return false;
        }
        let Some((kind, ident)) = word.split_once(':') else {
            return false;
        };
        Self::KINDS.contains(&kind) && !Coerce::strip(ident).is_empty() && word.chars().all(|letter| !letter.is_control())
    }

    fn keys(layout: Option<&Value>) -> Vec<Value> {
        let stored = layout.and_then(|layout| layout.get("serverOrder")).and_then(Value::as_array).into_iter().flatten();
        let mut keys: Vec<Value> = Vec::new();
        for key in stored {
            if Self::is_key(key) && !keys.contains(key) {
                keys.push(key.clone());
            }
        }
        keys
    }

    fn revision(layout: Option<&Value>) -> i64 {
        // absent-ok: a layout that was never saved is at its first revision.
        layout.and_then(|layout| layout.get("serverOrderRev")).and_then(Value::as_i64).filter(|rev| *rev >= 0).unwrap_or(0)
    }

    /// What the topology payload carries under `layout`.
    pub fn layout_of(layout: Option<&Value>) -> Map<String, Value> {
        let mut out = Map::new();
        out.insert("serverOrder".to_string(), Value::Array(Self::keys(layout)));
        out.insert("serverOrderRev".to_string(), json!(Self::revision(layout)));
        out
    }

    /// `order` stored whole, after checking it whole; what is stored now.
    pub fn save(app: &App, order: Option<&Value>) -> Result<Value, AppError> {
        let order = order.and_then(Value::as_array).ok_or_else(|| AppError::new("order must be a list of card keys"))?;
        if order.len() > Self::LIMIT {
            return Err(AppError::new(format!("order holds {} keys; at most {}", order.len(), Self::LIMIT)));
        }
        let mut seen: Vec<&Value> = Vec::new();
        for (at, key) in order.iter().enumerate() {
            if !Self::is_key(key) {
                let shown: String = Coerce::str_of(Some(key)).chars().take(80).collect();
                return Err(AppError::new(format!(
                    "order[{at}] is not a card key (node:<machine id> or cloud:<account id>): {}",
                    PyRepr::of(&shown)
                )));
            }
            if seen.contains(&key) {
                return Err(AppError::new(format!("order lists {} twice", Coerce::str_of(Some(key)))));
            }
            seen.push(key);
        }
        let layout = LayoutSection::saved(app, |layout| {
            let rev = Self::revision(Some(layout)) + 1;
            Coerce::put(layout, "serverOrder", Value::Array(order.clone()));
            Coerce::put(layout, "serverOrderRev", json!(rev));
        });
        Ok(json!({"ok": true, "order": Self::keys(Some(&layout)), "rev": Self::revision(Some(&layout))}))
    }
}

/// The operator's order of the clients' cards (1.3.503).
pub struct ClientOrder;

impl ClientOrder {
    const LIMIT: usize = 500;

    fn is_port(value: &Value) -> bool {
        value.as_i64().is_some_and(|port| 0 < port && port < 65536)
    }

    fn ports(layout: Option<&Value>) -> Vec<Value> {
        let stored = layout.and_then(|layout| layout.get("clientOrder")).and_then(Value::as_array).into_iter().flatten();
        let mut ports: Vec<Value> = Vec::new();
        for port in stored {
            if Self::is_port(port) && !ports.contains(port) {
                ports.push(port.clone());
            }
        }
        ports
    }

    fn revision(layout: Option<&Value>) -> i64 {
        // absent-ok: a layout that was never saved is at its first revision.
        layout.and_then(|layout| layout.get("clientOrderRev")).and_then(Value::as_i64).filter(|rev| *rev >= 0).unwrap_or(0)
    }

    /// What the topology payload carries under `layout` for the clients.
    pub fn layout_of(layout: Option<&Value>) -> Map<String, Value> {
        let mut out = Map::new();
        out.insert("clientOrder".to_string(), Value::Array(Self::ports(layout)));
        out.insert("clientOrderRev".to_string(), json!(Self::revision(layout)));
        out
    }

    /// `order` stored whole, after checking it whole.
    pub fn save(app: &App, order: Option<&Value>) -> Result<Value, AppError> {
        let order = order.and_then(Value::as_array).ok_or_else(|| AppError::new("order must be a list of the clients' ports"))?;
        if order.len() > Self::LIMIT {
            return Err(AppError::new(format!("order holds {} ports; at most {}", order.len(), Self::LIMIT)));
        }
        let mut seen: Vec<&Value> = Vec::new();
        for (at, port) in order.iter().enumerate() {
            if !Self::is_port(port) {
                let shown: String = Coerce::str_of(Some(port)).chars().take(40).collect();
                return Err(AppError::new(format!("order[{at}] is not a port: {}", PyRepr::of(&shown))));
            }
            if seen.contains(&port) {
                return Err(AppError::new(format!("order lists {} twice", Coerce::str_of(Some(port)))));
            }
            seen.push(port);
        }
        let layout = LayoutSection::saved(app, |layout| {
            let rev = Self::revision(Some(layout)) + 1;
            Coerce::put(layout, "clientOrder", Value::Array(order.clone()));
            Coerce::put(layout, "clientOrderRev", json!(rev));
        });
        Ok(json!({"ok": true, "order": Self::ports(Some(&layout)), "rev": Self::revision(Some(&layout))}))
    }
}

/// The topology's `layout`, made a section when the document holds something else.
struct LayoutSection;

impl LayoutSection {
    fn saved(app: &App, change: impl FnOnce(&mut Value)) -> Value {
        app.admin.saving(|doc| {
            let store = AdminStore::topology(doc);
            if !store.get("layout").is_some_and(Value::is_object) {
                store.insert("layout".to_string(), json!({}));
            }
            match store.get_mut("layout") {
                Some(layout) => {
                    change(layout);
                    layout.clone()
                }
                None => json!({}),
            }
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_card_key_names_its_kind_and_what_it_is() {
        assert!(ServerOrder::is_key(&json!("node:a")));
        assert!(ServerOrder::is_key(&json!("cloud:a b")));
        for bad in [
            json!("x:a"),
            json!("node:"),
            json!("node: "),
            json!(5),
            json!("node:a\nb"),
            json!(format!("node:{}", "x".repeat(200))),
        ] {
            assert!(!ServerOrder::is_key(&bad), "{bad}");
        }
    }

    #[test]
    fn a_stored_order_is_read_without_what_it_cannot_be() {
        let layout = json!({"serverOrder": ["node:a", "node:a", "bad", 5], "serverOrderRev": -1, "clientOrder": [5, 5, "x", 70000, true], "clientOrderRev": 3});
        assert_eq!(ServerOrder::layout_of(Some(&layout))["serverOrder"], json!(["node:a"]));
        assert_eq!(ServerOrder::layout_of(Some(&layout))["serverOrderRev"], 0);
        assert_eq!(ClientOrder::layout_of(Some(&layout))["clientOrder"], json!([5]));
        assert_eq!(ClientOrder::layout_of(Some(&layout))["clientOrderRev"], 3);
        assert_eq!(ClientOrder::layout_of(None)["clientOrderRev"], 0);
    }
}
