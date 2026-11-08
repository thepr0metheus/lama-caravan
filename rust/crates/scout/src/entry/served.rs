//! The names a running cell's server answers to: its own `GET /v1/models`, each model's `id` and the `aliases` `llama-server` lists, asked once per start of the cell. vLLM refuses a request for a name it does not serve; `llama-server` and the caravan's own cells take any.

use crate::http_client::HttpClient;
use rules::CellDoor;
use serde_json::Value;
use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, PoisonError};
use std::time::Duration;

/// Which copy of a model takes a request: the running copy with the fewest requests in work, by its server's own count; a count it does not say is taken as none. A tie goes to the next copy in turn, so equal copies share the work. One copy is not asked about at all.
#[derive(Debug, Default)]
pub struct CopyTurns {
    turn: Mutex<usize>,
}

impl CopyTurns {
    /// The port to hand the request to.
    pub fn pick(&self, ports: &[i64], busy: impl Fn(i64) -> i64) -> Option<i64> {
        if ports.len() < 2 {
            return ports.first().copied();
        }
        let start = {
            let mut turn = self.turn.lock().unwrap_or_else(PoisonError::into_inner);
            let start = *turn % ports.len();
            *turn = turn.wrapping_add(1);
            start
        };
        let (head, tail) = ports.split_at(start);
        tail.iter().chain(head).copied().min_by_key(|port| busy(*port))
    }
}

/// When its record says the cell started, and what it answered then.
type KeptNames = (Option<Value>, Vec<String>);

/// The names asked and kept.
pub struct ServedNames {
    http: Arc<HttpClient>,
    kept: Mutex<BTreeMap<i64, KeptNames>>,
}

impl ServedNames {
    const TIMEOUT: Duration = Duration::from_secs(2);

    /// Nothing asked yet.
    pub fn new(http: Arc<HttpClient>) -> Self {
        Self { http, kept: Mutex::new(BTreeMap::new()) }
    }

    /// A server that answers without a list (404: a cell of the caravan's own) names nothing: an empty list, kept. One that does not answer, or fails (503 while it loads), is not known: `None`, not kept: asked again next time.
    pub fn of(&self, port: i64, since: Option<&Value>) -> Option<Vec<String>> {
        if let Some((_, names)) =
            self.kept.lock().unwrap_or_else(PoisonError::into_inner).get(&port).filter(|(said, _)| said.as_ref() == since)
        {
            return Some(names.clone());
        }
        let answer =
            self.http.answer("GET", &format!("http://{}:{port}/v1/models", CellDoor::LISTEN), &[], &[], Self::TIMEOUT).ok()?;
        let status = answer.head.status;
        let raw = answer.text(64 << 20).ok()?;
        if status >= 500 {
            return None;
        }
        let names = if status == 200 { Self::parse(&raw) } else { Vec::new() };
        self.kept.lock().unwrap_or_else(PoisonError::into_inner).insert(port, (since.cloned(), names.clone()));
        Some(names)
    }

    /// `{data: [{id, aliases?}]}`: the ids, then the aliases, each once, in the order the server says them.
    pub fn parse(raw: &[u8]) -> Vec<String> {
        let payload = serde_json::from_slice::<Value>(raw).ok();
        let items = payload.as_ref().and_then(|payload| payload.get("data")).and_then(Value::as_array);
        let mut names: Vec<String> = Vec::new();
        for item in items.into_iter().flatten().filter(|item| item.is_object()) {
            let aliases = item.get("aliases").and_then(Value::as_array).into_iter().flatten();
            for name in item.get("id").into_iter().chain(aliases).filter_map(Value::as_str) {
                let name = rules::Coerce::strip(name);
                if !name.is_empty() && !names.iter().any(|said| said == name) {
                    names.push(name.to_string());
                }
            }
        }
        names
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_names_are_the_ids_then_the_aliases_each_once() {
        let said = br#"{"data": [{"id": "a", "aliases": ["b", "a", 3, " c "]}, "text", {"id": 5}, {"id": "d"}]}"#;
        assert_eq!(ServedNames::parse(said), ["a", "b", "c", "d"]);
        assert!(ServedNames::parse(b"nonsense").is_empty());
        assert!(ServedNames::parse(br#"{"data": 5}"#).is_empty());
    }

    #[test]
    fn the_least_busy_copy_takes_it_and_a_tie_goes_in_turn() {
        let turns = CopyTurns::default();
        assert_eq!(turns.pick(&[], |_| 0), None);
        assert_eq!(turns.pick(&[7], |_| 9), Some(7));
        assert_eq!(turns.pick(&[1, 2], |port| if port == 1 { 5 } else { 0 }), Some(2));
        assert_eq!(turns.pick(&[1, 2], |port| if port == 1 { 0 } else { 5 }), Some(1));
        let first = turns.pick(&[1, 2], |_| 0);
        let second = turns.pick(&[1, 2], |_| 0);
        assert_ne!(first, second);
    }
}
