//! The machines with a scout, second by second, for the board's charts. Pulled only while a board is open.

use super::reports::FleetReads;
use super::scout::ScoutCall;
use crate::app::App;
use rules::Coerce;
use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::sync::{Arc, Mutex, PoisonError};

/// The samples held.
#[derive(Default)]
pub struct TelemetryMemory {
    held: Mutex<TelemetryBook>,
}

#[derive(Default)]
struct TelemetryBook {
    rows: BTreeMap<String, VecDeque<Value>>,
    busy: BTreeSet<String>,
    last: BTreeMap<String, f64>,
}

/// Each scout's machine sampled a second apart.
pub struct HostTelemetry;

impl HostTelemetry {
    const MIN_INTERVAL: f64 = 1.0;
    const RETENTION: f64 = 600.0;

    fn moment(row: &Value) -> f64 {
        // absent-ok: every row held has a moment: `pull` kept only those.
        row.get("t").and_then(Value::as_f64).unwrap_or(0.0)
    }

    fn sampled(host: &Value) -> bool {
        host.get("telemetry").is_some_and(Value::is_object) && host.get("state").and_then(Value::as_str) == Some("online")
    }

    /// A pull started of every sampled machine not pulled in the last second and not being pulled now.
    pub fn kick(app: &Arc<App>) {
        let now = app.clock.monotonic();
        for host in FleetReads::of(app).hosts() {
            let host_id = Coerce::text(host.get("id"));
            if host_id.is_empty() || !Self::sampled(&host) {
                continue;
            }
            {
                let mut book = app.telemetry.held.lock().unwrap_or_else(PoisonError::into_inner);
                if book.busy.contains(&host_id) || book.last.get(&host_id).is_some_and(|last| now - last < Self::MIN_INTERVAL) {
                    continue;
                }
                book.busy.insert(host_id.clone());
                book.last.insert(host_id.clone(), now);
            }
            let held = Arc::clone(app);
            let started = std::thread::Builder::new().name("host-telemetry".to_string()).spawn({
                let host_id = host_id.clone();
                move || Self::pull(&held, &host_id)
            });
            if started.is_err() {
                app.telemetry.held.lock().unwrap_or_else(PoisonError::into_inner).busy.remove(&host_id);
            }
        }
    }

    fn newest(app: &App, host_id: &str) -> f64 {
        let book = app.telemetry.held.lock().unwrap_or_else(PoisonError::into_inner);
        // absent-ok: a machine with no rows has heard nothing yet.
        book.rows.get(host_id).and_then(VecDeque::back).map_or(0.0, Self::moment)
    }

    fn pull(app: &App, host_id: &str) {
        if let Ok(scout) = ScoutCall::of_host(app, host_id) {
            let since = Self::newest(app, host_id);
            let shown = if since.fract() == 0.0 { format!("{}", since as i64) } else { since.to_string() };
            let answer = scout.read(&format!("/api/telemetry?since={shown}"), 2);
            if Coerce::truthy(answer.get("ok")) {
                let fresh = answer.get("samples").and_then(Value::as_array).into_iter().flatten();
                let fresh: Vec<&Value> =
                    fresh.filter(|row| row.is_object() && row.get("t").is_some_and(Value::is_number)).collect();
                let mut book = app.telemetry.held.lock().unwrap_or_else(PoisonError::into_inner);
                let rows = book.rows.entry(host_id.to_string()).or_default();
                for row in fresh {
                    if rows.back().is_none_or(|last| Self::moment(row) > Self::moment(last)) {
                        rows.push_back(row.clone());
                    }
                }
                while let (Some(first), Some(last)) = (rows.front(), rows.back()) {
                    if Self::moment(first) >= Self::moment(last) - Self::RETENTION {
                        break;
                    }
                    rows.pop_front();
                }
            }
        }
        app.telemetry.held.lock().unwrap_or_else(PoisonError::into_inner).busy.remove(host_id);
    }

    /// The board's `hostsSince`, "id:t,id:t", as `{host id: moment}`.
    pub fn held_of(raw: &str) -> BTreeMap<String, i64> {
        let mut held = BTreeMap::new();
        for part in raw.split(',') {
            if let Some((host_id, moment)) = Coerce::strip(part).rsplit_once(':')
                && !host_id.is_empty()
                && let Ok(moment) = moment.parse::<f64>()
            {
                held.insert(host_id.to_string(), moment as i64);
            }
        }
        held
    }

    /// `{host id: rows after what the board holds}`.
    pub fn since(app: &App, held: &BTreeMap<String, i64>) -> Value {
        let book = app.telemetry.held.lock().unwrap_or_else(PoisonError::into_inner);
        let mut out = Map::new();
        for (host_id, rows) in &book.rows {
            // absent-ok: a page that holds nothing of a machine wants all of it.
            let after = held.get(host_id).copied().unwrap_or(0) as f64;
            let fresh: Vec<Value> = rows.iter().filter(|row| Self::moment(row) > after).cloned().collect();
            if !fresh.is_empty() {
                out.insert(host_id.clone(), Value::Array(fresh));
            }
        }
        Value::Object(out)
    }

    /// What the board's monitor read carries.
    pub fn watch(app: &Arc<App>, raw_held: &str) -> Value {
        Self::kick(app);
        Self::since(app, &Self::held_of(raw_held))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn what_the_board_holds_reads_from_its_word() {
        let held = HostTelemetry::held_of("a:5,b:c:7.9, x ,:3,d:no");
        assert_eq!(held.get("a"), Some(&5));
        assert_eq!(held.get("b:c"), Some(&7));
        assert_eq!(held.len(), 2);
    }
}
