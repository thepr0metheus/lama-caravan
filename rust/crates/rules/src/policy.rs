//! The proxy's settings: the part of the file's `policy` it goes by.

use crate::coerce::Coerce;
use crate::model_queue::ModelQueuePolicy;
use serde_json::Value;

/// What `policy` in `agent-proxies.json` says, each value within its bounds. The file on a running caravan says every one.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Policy {
    /// Places when a model does not say its own.
    pub max_slots: i64,
    /// Seconds a request waits for a cell that answers "Loading model".
    pub loading_model_wait_sec: i64,
    /// The model queue's settings.
    pub queue: ModelQueuePolicy,
}

impl Default for Policy {
    fn default() -> Self {
        Self::read(None)
    }
}

impl Policy {
    /// The seconds between keepalives of a waiting or a slow request.
    pub const KEEPALIVE_SEC: f64 = 20.0;

    /// The settings of `raw`, the file's `policy`.
    pub fn read(raw: Option<&Value>) -> Self {
        let empty = Value::Null;
        let raw = raw.unwrap_or(&empty);
        let limit_sec = Self::bounded(raw, "queueLimitSec", 0, 0, 3600);
        let yield_sec = Self::bounded(raw, "queueYieldSec", 0, 0, 3600);
        Self {
            max_slots: Self::bounded(raw, "maxSlots", 1, 1, 64),
            loading_model_wait_sec: Self::bounded(raw, "loadingModelWaitSec", 60, 0, 900),
            queue: ModelQueuePolicy {
                yield_sec: if limit_sec > 0 { yield_sec.min(limit_sec) } else { yield_sec },
                limit_sec,
                client_timeout_sec: Self::bounded(raw, "clientTimeoutSec", 3600, 60, 86_400),
            },
        }
    }

    /// `max(low, min(high, int(policy.get(key, default))))`; a value that does not read is its default.
    fn bounded(raw: &Value, key: &str, default: i64, low: i64, high: i64) -> i64 {
        let said = raw.get(key).map_or(Some(default), Coerce::int).unwrap_or(default);
        said.min(high).max(low)
    }
}
