//! What a client of the entry is closed to.

use crate::coerce::Coerce;
use serde_json::Value;
use std::collections::BTreeSet;

/// What a client of the entry is closed to: its route's `deny`.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ClientDeny {
    keys: BTreeSet<String>,
}

impl ClientDeny {
    /// The route's field.
    pub const FIELD: &'static str = "deny";
    const KINDS: [&'static str; 4] = ["pool", "model", "account", "host"];
    const MAX: usize = 200;
    const KEY_MAX: usize = 200;

    /// `raw` as a route keeps it: the distinct keys of a known kind.
    pub fn clean(raw: Option<&Value>) -> Self {
        let mut keys = BTreeSet::new();
        for item in raw.and_then(Value::as_array).into_iter().flatten() {
            // absent-ok: what is not a string is no key, and an empty one fails `known` below.
            let key = item.as_str().map(Coerce::strip).unwrap_or_default();
            let known = key.split_once(':').is_some_and(|(kind, rest)| Self::KINDS.contains(&kind) && !rest.is_empty());
            if known && key.chars().count() <= Self::KEY_MAX && keys.len() < Self::MAX {
                keys.insert(key.to_string());
            }
        }
        Self { keys }
    }

    /// The keys, in their order of comparison.
    pub fn keys(&self) -> impl Iterator<Item = &str> {
        self.keys.iter().map(String::as_str)
    }

    /// Whether the client may not call the pool of this id by its name.
    pub fn closes_pool(&self, pool_id: &str) -> bool {
        self.keys.contains(&format!("pool:{pool_id}"))
    }

    /// Whether the client may not call the model standing at `place`: the model itself closed, or its account, or its machine.
    pub fn closes(&self, place: &str, account: &str, host: &str) -> bool {
        let source = |kind: &str, id: &str| !id.is_empty() && self.keys.contains(&format!("{kind}:{id}"));
        self.keys.contains(&format!("model:{place}")) || source("account", account) || source("host", host)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn refusals_are_kept_up_to_their_limits() {
        let many: Vec<String> = (0..205).map(|at| format!("pool:p{at:03}")).collect();
        assert_eq!(ClientDeny::clean(Some(&json!(many))).keys().count(), 200);
        let at_limit = format!("pool:{}", "x".repeat(195));
        assert_eq!(at_limit.chars().count(), 200);
        assert_eq!(ClientDeny::clean(Some(&json!([at_limit]))).keys().count(), 1);
        let past_limit = format!("pool:{}", "x".repeat(196));
        assert_eq!(ClientDeny::clean(Some(&json!([past_limit]))).keys().count(), 0);
    }

    #[test]
    fn a_source_closes_what_stands_on_it_and_nothing_closes_by_an_empty_name() {
        let deny = ClientDeny::clean(Some(&json!(["model:mm:a", "account:acc", "host:box", "pool:p"])));
        assert!(deny.closes("mm:a", "", ""));
        assert!(deny.closes("mm:b", "acc", ""));
        assert!(deny.closes("mm:b", "", "box"));
        assert!(!deny.closes("mm:b", "other", "other"));
        assert!(!ClientDeny::clean(Some(&json!(["model:mm:a"]))).closes("mm:b", "", ""));
        assert!(deny.closes_pool("p"));
        assert!(!deny.closes_pool("q"));
    }
}
