//! Queue-wait thresholds per client.

use super::config::ProxiesConfig;
use super::dsl::RouterDsl;
use crate::app::App;
use rules::Coerce;
use serde_json::{Value, json};
use std::sync::{Mutex, PoisonError};
use wire::HttpDate;

/// The last computed thresholds.
#[derive(Default)]
pub struct ThresholdMemory {
    data: Mutex<Option<Value>>,
}

/// The thresholds of this controller.
pub struct QueueThresholds<'app> {
    app: &'app App,
}

impl<'app> QueueThresholds<'app> {
    /// How often they are computed again.
    pub const REFRESH_SECONDS: u64 = 6 * 3600;

    /// The thresholds of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// `round(x)` of Python: a half goes to the even neighbour.
    fn rounded(value: f64) -> i64 {
        let floor = value.floor();
        let gap = value - floor;
        let up = gap > 0.5 || (gap == 0.5 && (floor as i64) % 2 != 0);
        (if up { floor + 1.0 } else { floor }) as i64
    }

    fn pct_of(policy: &Value, key: &str, otherwise: i64) -> i64 {
        policy.get(key).filter(|said| Coerce::truthy(Some(*said))).and_then(Coerce::int).unwrap_or(otherwise)
    }

    fn entry_of(route: &Value, globals: (i64, i64, i64)) -> Option<(Value, (i64, i64, i64))> {
        if !route.is_object() {
            return None;
        }
        let kind = {
            let said = Coerce::text(route.get("upstreamType"));
            if said.is_empty() { "llama".to_string() } else { said }
        };
        // absent-ok: `int(route.get("clientTimeoutSeconds") or 0)`: a route with no wait has no thresholds.
        let wait = Coerce::whole(route.get("clientTimeoutSeconds"));
        if kind == "cloud" || wait == 0 {
            return None;
        }
        let effective = |key: &str, global: i64| {
            route.get(key).filter(|said| !said.is_null()).and_then(Coerce::int).map_or(global, |said| said.clamp(0, 100))
        };
        let cloud = effective("cloudFallbackPct", globals.0);
        let priority = effective("priorityPreemptPct", globals.1);
        let abort = effective("queueAbortPct", globals.2);
        let share = |pct: i64| Self::rounded(wait as f64 * pct as f64 / 100.0);
        let has = |key: &str| route.get(key).is_some_and(|said| !said.is_null());
        let mut entry = json!({
            "id": route.get("id"), "label": route.get("label"),
            "clientTimeoutSeconds": wait,
            "queueAbortSec": share(abort), "priorityPreemptSec": share(priority),
            "effectiveCloudPct": cloud, "effectivePriorityPct": priority, "effectiveAbortPct": abort,
            "hasCloudOverride": has("cloudFallbackPct"), "hasPriorityOverride": has("priorityPreemptPct"), "hasAbortOverride": has("queueAbortPct"),
        });
        if Coerce::truthy(route.get("cloudFallbackProviderId")) {
            Coerce::put(&mut entry, "cloudFallbackSec", json!(share(cloud)));
        }
        Some((entry, (cloud, priority, abort)))
    }

    /// Per-proxy thresholds from the policy and each route's wait, kept and mirrored into the proxy's settings. `None` when the settings do not read.
    pub fn compute(&self) -> Option<Value> {
        let config = ProxiesConfig::of(self.app);
        let loaded = config.load().ok()?;
        let policy = loaded
            .get("policy")
            .filter(|policy| Coerce::truthy(Some(*policy)))
            .cloned()
            .unwrap_or_else(|| RouterDsl::policy(None));
        let globals = (
            Self::pct_of(&policy, "cloudFallbackPct", 20),
            Self::pct_of(&policy, "priorityPreemptPct", 50),
            Self::pct_of(&policy, "queueAbortPct", 85),
        );
        let (mut proxies, mut last) = (Vec::new(), None);
        for route in loaded.get("routes").and_then(Value::as_array).into_iter().flatten() {
            if let Some((entry, shares)) = Self::entry_of(route, globals) {
                proxies.push(entry);
                last = Some(shares);
            }
        }
        // No route waits for a local answer: there is nothing to compute, and the last result stays. The board reads null before the first one.
        let shown = last?;
        let result = json!({
            "proxies": proxies,
            "policy": {"cloudFallbackPct": shown.0, "priorityPreemptPct": shown.1, "queueAbortPct": shown.2},
            "computedAt": HttpDate::iso_z(self.app.now_whole()),
        });
        *self.app.thresholds.data.lock().unwrap_or_else(PoisonError::into_inner) = Some(result.clone());
        let mut payload = config.read_payload();
        if payload.is_object() && payload.get("computedThresholds") != Some(&result) {
            Coerce::put(&mut payload, "computedThresholds", result.clone());
            drop(config.write_payload(payload));
        }
        Some(result)
    }

    /// The last computed thresholds; `None` before the first computation.
    pub fn latest(&self) -> Option<Value> {
        self.app.thresholds.data.lock().unwrap_or_else(PoisonError::into_inner).clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_route_with_a_wait_gets_shares_of_it() {
        let route = json!({"id": "a", "clientTimeoutSeconds": 100, "queueAbortPct": 90, "cloudFallbackProviderId": "p"});
        let (entry, shares) = QueueThresholds::entry_of(&route, (20, 50, 85)).unwrap();
        assert_eq!(entry["queueAbortSec"], 90);
        assert_eq!(entry["priorityPreemptSec"], 50);
        assert_eq!(entry["cloudFallbackSec"], 20);
        assert_eq!(entry["hasAbortOverride"], true);
        assert_eq!(entry["hasCloudOverride"], false);
        assert_eq!(shares, (20, 50, 90));
    }

    #[test]
    fn a_cloud_route_or_one_with_no_wait_has_none() {
        assert!(QueueThresholds::entry_of(&json!({"upstreamType": "cloud", "clientTimeoutSeconds": 5}), (1, 2, 3)).is_none());
        assert!(QueueThresholds::entry_of(&json!({"id": "a"}), (1, 2, 3)).is_none());
    }

    #[test]
    fn a_half_rounds_to_the_even_neighbour() {
        assert_eq!(QueueThresholds::rounded(2.5), 2);
        assert_eq!(QueueThresholds::rounded(3.5), 4);
        assert_eq!(QueueThresholds::rounded(3.2), 3);
    }
}
