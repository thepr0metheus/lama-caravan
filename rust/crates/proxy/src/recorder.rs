//! A journal's row.

use crate::board::Board;
use crate::clock::Clock;
use files::Journal;
use os::LocalTime;
use serde_json::{Map, Value, json};
use std::sync::Arc;

/// Writes rows in the journal's format. A failed write never fails the request it is about: the board counts it.
pub struct Recorder {
    journal: Journal,
    board: Arc<Board>,
    clock: Arc<dyn Clock>,
}

impl Recorder {
    /// The word on each of this process's rows, so that a reader can tell the two proxies apart in one file.
    pub const WHO: &'static str = "rust";

    /// A recorder into `journal`.
    pub fn new(journal: Journal, board: Arc<Board>, clock: Arc<dyn Clock>) -> Self {
        Self { journal, board, clock }
    }

    /// One row. `fields` are added last and win, as Python's `**fields` do: `upstream_started` says its own `queue`.
    pub fn event(&self, event: &str, route: &str, request_id: &str, item: Option<&Value>, fields: Value) {
        let now = self.clock.epoch();
        let row = self.row(now, event, route, request_id, item, fields);
        if self.journal.append(now as i64, row.to_string().as_bytes()).is_err() {
            self.board.count_journal_failure();
        }
    }

    fn row(&self, now: f64, event: &str, route: &str, request_id: &str, item: Option<&Value>, fields: Value) -> Value {
        // absent-ok: `route_label or item.route or ""`: a row with neither says "" there.
        let said = |name: &str| item.and_then(|item| item.get(name)).and_then(Value::as_str).unwrap_or_default().to_string();
        let route = if route.is_empty() { said("route") } else { route.to_string() };
        let id = if request_id.is_empty() { said("id") } else { request_id.to_string() };
        let mut row: Map<String, Value> = Map::new();
        row.insert("time".into(), json!(now as i64));
        row.insert("timeIso".into(), json!(LocalTime::of(now as i64).map(|moment| moment.iso())));
        row.insert("event".into(), json!(event));
        row.insert("route".into(), json!(route));
        row.insert("requestId".into(), json!(id));
        row.insert("item".into(), item.cloned().unwrap_or_else(|| json!({})));
        row.insert("queue".into(), json!(self.board.pending_items()));
        row.insert("proxy".into(), json!(Self::WHO));
        if let Value::Object(fields) = fields {
            row.extend(fields);
        }
        Value::Object(row)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::clock::SystemClock;
    use std::fs;

    fn folder(name: &str) -> std::path::PathBuf {
        std::env::temp_dir().join(format!("caravan-recorder-{name}-{}", std::process::id()))
    }

    fn rows_in(folder: &std::path::Path) -> Vec<Value> {
        let mut rows = Vec::new();
        for file in fs::read_dir(folder).unwrap() {
            for line in fs::read_to_string(file.unwrap().path()).unwrap().lines() {
                rows.push(serde_json::from_str(line).unwrap());
            }
        }
        rows
    }

    #[test]
    fn a_row_says_what_a_python_row_says_and_who_wrote_it() {
        let place = folder("row");
        let board = Arc::new(Board::default());
        board.add_active("a", "client-a", json!({"id": "r1"}));
        let recorder = Recorder::new(Journal::new(place.clone(), None), board, Arc::new(SystemClock::new()));
        recorder.event("received", "a", "r1", Some(&json!({"id": "r1", "route": "a"})), json!({"status": 200}));
        recorder.event("blocked", "", "", Some(&json!({"id": "r2", "route": "b"})), json!({"queue": {"queuedMs": 5}}));
        let rows = rows_in(&place);
        assert_eq!(rows[0]["event"], json!("received"));
        assert_eq!(rows[0]["requestId"], json!("r1"));
        assert!(rows[0].get("active").is_none(), "half of a row's weight, and nobody read it");
        assert_eq!(rows[0]["queue"], json!([]));
        assert_eq!(rows[0]["status"], json!(200));
        assert_eq!(rows[0]["proxy"], json!("rust"));
        assert!(rows[0]["timeIso"].as_str().unwrap().contains('T'));
        assert_eq!((rows[1]["route"].clone(), rows[1]["requestId"].clone()), (json!("b"), json!("r2")));
        assert_eq!(rows[1]["queue"], json!({"queuedMs": 5}));
        fs::remove_dir_all(&place).unwrap();
    }

    #[test]
    fn a_write_that_fails_is_counted_and_fails_nothing() {
        let place = folder("fail");
        fs::write(&place, b"a file where the folder should be").unwrap();
        let board = Arc::new(Board::default());
        let recorder = Recorder::new(Journal::new(place.clone(), None), board.clone(), Arc::new(SystemClock::new()));
        recorder.event("received", "a", "r1", None, json!({}));
        assert_eq!(board.state_json(0.0, 0.0, 0, "")["counts"]["journalFailures"], json!(1));
        fs::remove_file(&place).unwrap();
    }
}
