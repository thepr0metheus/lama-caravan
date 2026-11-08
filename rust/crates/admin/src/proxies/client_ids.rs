//! A client of the entry is known by its record's id (the owner, 2026-11-07). It has had no port of its own since 2026-11-02: the
//! number 23001… that named it was a record's, never a port anyone listened on. What the journal, the token history and the
//! monitor wrote under that number before the move is found by the one table that says which id each number became.

use net::Randomness;
use rules::{AppError, Coerce, RouteId};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};

mod given;
pub use given::ClientIdsGiven;

/// The ids of the clients' records: read and given.
pub struct ClientIds;

impl ClientIds {
    /// The record's field.
    pub const FIELD: &'static str = "id";
    /// What a given id starts with: a reader of the journal sees what it names.
    const PREFIX: &'static str = "client-";
    /// How many draws a new id may take before the system's randomness is called broken.
    const DRAWS: usize = 16;

    /// The id a record names, cleaned; "" for none.
    pub fn of(route: &Value) -> String {
        Coerce::stripped(route.get(Self::FIELD))
    }

    /// The id a request names, or the refusal that says how a client is named. A request that still names a client by its old
    /// number is refused out loud: read as no filter at all, it would answer every client's rows as this one's.
    pub fn asked(said: Option<&Value>, port_said: bool) -> Result<String, AppError> {
        if port_said {
            return Err(AppError::new("a client has no port: name it by its record's id, routeId"));
        }
        let id = Coerce::stripped(said);
        if !RouteId::acceptable(&id) {
            return Err(AppError::new("routeId must be a client's id: Latin letters, digits, - and _"));
        }
        Ok(id)
    }

    /// A new id none of `taken` has.
    pub fn mint(taken: &BTreeSet<String>) -> Result<String, AppError> {
        for _ in 0..Self::DRAWS {
            let bytes = Randomness::bytes(4).ok_or_else(|| AppError::with_status("the system gives no random bytes", 500))?;
            let id = format!("{}{}", Self::PREFIX, bytes.iter().map(|byte| format!("{byte:02x}")).collect::<String>());
            if !taken.contains(&id) {
                return Ok(id);
            }
        }
        Err(AppError::with_status("no free client id after 16 draws: the system's randomness repeats itself", 500))
    }

    /// The ids `routes` hold.
    pub fn taken(routes: &[Value]) -> BTreeSet<String> {
        routes.iter().map(Self::of).filter(|id| !id.is_empty()).collect()
    }
}

/// The numbers the clients had until 2026-11-07, each with the id it became. History, not a way in: nothing listens on them, and the
/// board shows none.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct FormerPorts {
    by_port: BTreeMap<i64, String>,
}

impl FormerPorts {
    /// The document's field.
    pub const FIELD: &'static str = "formerPorts";

    /// The table `payload` keeps; empty for a caravan whose clients never had numbers.
    pub fn of(payload: &Value) -> Self {
        let rows = payload.get(Self::FIELD).and_then(Value::as_object).into_iter().flatten();
        let by_port = rows
            .filter_map(|(port, id)| {
                let id = Coerce::stripped(Some(id));
                Some((port.parse::<i64>().ok().filter(|port| *port > 0)?, id)).filter(|(_, id)| RouteId::acceptable(id))
            })
            .collect();
        Self { by_port }
    }

    /// The table as the document keeps it.
    pub fn json(&self) -> Value {
        let rows: Map<String, Value> = self.by_port.iter().map(|(port, id)| (port.to_string(), json!(id))).collect();
        Value::Object(rows)
    }

    /// `port` became `id`; a number that already became one keeps it.
    pub fn note(&mut self, port: i64, id: &str) -> bool {
        if port <= 0 || self.by_port.contains_key(&port) {
            return false;
        }
        self.by_port.insert(port, id.to_string());
        true
    }

    /// The id a number became.
    pub fn id_of(&self, port: i64) -> Option<&str> {
        self.by_port.get(&port).map(String::as_str)
    }

    /// The client a journal item, a token-history row or a monitor row belongs to: the id it says, else the id its old number
    /// became. `None` for one of no client: an entry's refusal before a key named anyone, or a number no client had.
    pub fn client_of(&self, item: &Value) -> Option<String> {
        let said = Coerce::stripped(item.get("routeId"));
        if !said.is_empty() {
            return Some(said);
        }
        let port = item.get("port").and_then(Value::as_i64)?;
        self.id_of(port).map(str::to_string)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_minted_id_is_new_and_reads_as_one() {
        let taken: BTreeSet<String> = ["client-00000000".to_string()].into();
        let id = ClientIds::mint(&taken).unwrap();
        assert!(id.starts_with("client-") && id.len() == 15 && RouteId::acceptable(&id), "{id}");
        assert!(!taken.contains(&id));
    }

    #[test]
    fn a_request_names_a_client_by_its_id_and_never_by_a_number() {
        assert_eq!(ClientIds::asked(Some(&json!(" client-1 ")), false).unwrap(), "client-1");
        assert!(ClientIds::asked(Some(&json!("client-1")), true).unwrap_err().message.contains("routeId"));
        assert!(ClientIds::asked(None, false).is_err());
        assert!(ClientIds::asked(Some(&json!("a b")), false).is_err());
    }

    #[test]
    fn an_old_row_is_its_client_s_by_the_number_it_had() {
        let former = FormerPorts::of(&json!({"formerPorts": {"23001": "client-h", "x": "client-x", "23002": "bad id"}}));
        assert_eq!(former.json(), json!({"23001": "client-h"}));
        assert_eq!(former.client_of(&json!({"port": 23001})).as_deref(), Some("client-h"));
        assert_eq!(former.client_of(&json!({"routeId": "client-n", "port": 23001})).as_deref(), Some("client-n"));
        assert_eq!(former.client_of(&json!({"port": 23009})), None);
        assert_eq!(former.client_of(&json!({"port": "entry"})), None);
        assert_eq!(former.client_of(&json!({"routeId": ""})), None);
    }

    #[test]
    fn a_number_becomes_one_id_once() {
        let mut former = FormerPorts::default();
        assert!(former.note(23001, "client-a"));
        assert!(!former.note(23001, "client-b"));
        assert!(!former.note(0, "client-c"));
        assert_eq!(former.id_of(23001), Some("client-a"));
    }
}
