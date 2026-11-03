//! What this process last heard about each subscription account's limit windows.
//! The Codex backend states both of an account's windows on every answer, a refusal included.

use rules::UsageWindow;
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::sync::{Mutex, PoisonError};

/// Per account, the last reading of its windows and when it was heard.
#[derive(Debug, Default)]
pub struct SubscriptionUsage {
    rows: Mutex<BTreeMap<String, (Vec<UsageWindow>, f64)>>,
}

impl SubscriptionUsage {
    /// Keeps a reading. An empty one leaves the last as it was: absence is not a reading.
    pub fn keep(&self, account: &str, windows: Vec<UsageWindow>, now: f64) {
        if !account.is_empty() && !windows.is_empty() {
            self.rows.lock().unwrap_or_else(PoisonError::into_inner).insert(account.to_string(), (windows, now));
        }
    }

    /// The account's last reading and when it was heard; `None`: never, not a made-up moment.
    pub fn reading(&self, account: &str) -> (Vec<UsageWindow>, Option<f64>) {
        let rows = self.rows.lock().unwrap_or_else(PoisonError::into_inner);
        rows.get(account).map_or_else(|| (Vec::new(), None), |(windows, at)| (windows.clone(), Some(*at)))
    }

    /// Every account's last reading, for the state file.
    pub fn snapshot(&self) -> Value {
        let rows = self.rows.lock().unwrap_or_else(PoisonError::into_inner);
        let mut out = Map::new();
        for (account, (windows, at)) in rows.iter() {
            let said: Vec<Value> = windows.iter().map(UsageWindow::as_json).collect();
            out.insert(account.clone(), json!({"windows": said, "readAt": at}));
        }
        Value::Object(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const WINDOW: UsageWindow = UsageWindow { seconds: 18_000, used_pct: 5, reset_at: None };

    #[test]
    fn an_empty_reading_leaves_the_last_as_it_was() {
        let usage = SubscriptionUsage::default();
        assert_eq!(usage.reading("a"), (Vec::new(), None));
        usage.keep("a", vec![WINDOW], 10.0);
        usage.keep("a", Vec::new(), 20.0);
        assert_eq!(usage.reading("a"), (vec![WINDOW], Some(10.0)));
        usage.keep("", vec![WINDOW], 30.0);
        assert_eq!(
            usage.snapshot(),
            json!({"a": {"windows": [{"seconds": 18000, "usedPct": 5, "resetAt": null}], "readAt": 10.0}})
        );
    }
}
