//! What the board reads of this process: the running and the recent requests, and what it has done. Kept
//! in a state file of its own.

use serde_json::{Value, json};
use std::collections::{BTreeMap, VecDeque};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Mutex, MutexGuard, PoisonError};

/// One route's requests.
#[derive(Debug, Default)]
struct AgentRow {
    label: String,
    port: i64,
    active: Vec<Value>,
    recent: VecDeque<Value>,
}

/// The state behind the lock.
#[derive(Debug, Default)]
struct BoardState {
    agents: BTreeMap<String, AgentRow>,
    pending: Vec<Value>,
    served: u64,
    journal_failures: u64,
    state_failures: u64,
}

/// The requests and the counts. A write of the file is another object's turn: changing a request here costs a lock and no
/// disk.
#[derive(Debug, Default)]
pub struct Board {
    state: Mutex<BoardState>,
    dirty: AtomicBool,
}

impl Board {
    /// How many finished requests a route keeps.
    const RECENT: usize = 20;

    fn lock(&self) -> MutexGuard<'_, BoardState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn touched(&self) {
        self.dirty.store(true, Ordering::Release);
    }

    /// What the state file says has changed outside the board.
    pub fn touch(&self) {
        self.touched();
    }

    /// Whether anything changed since the last call.
    pub fn take_dirty(&self) -> bool {
        self.dirty.swap(false, Ordering::AcqRel)
    }

    /// A request has begun.
    pub fn add_active(&self, label: &str, port: i64, item: Value) {
        {
            let mut state = self.lock();
            let row = state.agents.entry(port.to_string()).or_default();
            row.label = label.to_string();
            row.port = port;
            row.active.push(item);
        }
        self.touched();
    }

    /// Fields of a running request changed.
    pub fn update_active(&self, port: i64, id: &str, patch: Value) {
        let Value::Object(patch) = patch else {
            return;
        };
        {
            let mut state = self.lock();
            let row = state.agents.entry(port.to_string()).or_default();
            let found = row.active.iter_mut().find(|item| item.get("id").and_then(Value::as_str) == Some(id));
            if let Some(Value::Object(item)) = found {
                item.extend(patch);
            }
        }
        self.touched();
    }

    /// A request has ended, with its record.
    pub fn finish_active(&self, port: i64, id: &str, result: Value) {
        {
            let mut state = self.lock();
            let row = state.agents.entry(port.to_string()).or_default();
            row.active.retain(|item| item.get("id").and_then(Value::as_str) != Some(id));
            row.recent.push_back(result);
            while row.recent.len() > Self::RECENT {
                row.recent.pop_front();
            }
            state.served += 1;
        }
        self.touched();
    }

    /// A request began to wait.
    pub fn add_pending(&self, item: Value) {
        self.lock().pending.push(item);
    }

    /// One running request's record as it stands.
    pub fn active_item(&self, port: i64, id: &str) -> Option<Value> {
        let state = self.lock();
        let row = state.agents.get(&port.to_string())?;
        row.active.iter().find(|item| item.get("id").and_then(Value::as_str) == Some(id)).cloned()
    }

    /// A request stopped waiting.
    pub fn remove_pending(&self, id: &str) {
        self.lock().pending.retain(|item| item.get("id").and_then(Value::as_str) != Some(id));
    }

    /// The waiting requests: what a journal's row carries.
    pub fn pending_items(&self) -> Vec<Value> {
        self.lock().pending.clone()
    }

    /// A journal's row could not be written. A failed write must not fail a request; it is counted, so that it is not
    /// silent: the state file says how many.
    pub fn count_journal_failure(&self) {
        self.lock().journal_failures += 1;
        self.touched();
    }

    /// The state file could not be written.
    pub fn count_state_failure(&self) {
        self.lock().state_failures += 1;
    }

    /// The state file's document: `agents`, and the counts beside them.
    pub fn state_json(&self, now: f64, started_at: f64, pid: u32, commit: &str) -> Value {
        let state = self.lock();
        let agents: BTreeMap<&String, Value> = state
            .agents
            .iter()
            .map(|(port, row)| {
                (port, json!({"label": row.label, "port": row.port, "active": row.active, "recent": row.recent, "upstreamType": "cloud"}))
            })
            .collect();
        json!({
            "startedAt": started_at as i64,
            "time": now as i64,
            "pid": pid,
            "sourceCommit": commit,
            "agents": agents,
            "counts": {
                "served": state.served,
                "journalFailures": state.journal_failures,
                "stateFailures": state.state_failures,
            },
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_request_goes_from_running_to_recent() {
        let board = Board::default();
        board.add_active("hermes", 23001, json!({"id": "r1", "phase": "queued"}));
        assert!(board.take_dirty());
        assert!(!board.take_dirty());
        board.update_active(23001, "r1", json!({"phase": "upstream", "bytes": 5}));
        assert!(board.take_dirty());
        assert_eq!(board.active_item(23001, "r1"), Some(json!({"id": "r1", "phase": "upstream", "bytes": 5})));
        board.finish_active(23001, "r1", json!({"id": "r1", "status": 200}));
        let state = board.state_json(100.0, 50.0, 7, "abc");
        assert_eq!(state["agents"]["23001"]["active"], json!([]));
        assert_eq!(state["agents"]["23001"]["recent"], json!([{"id": "r1", "status": 200}]));
        assert_eq!(state["agents"]["23001"]["label"], json!("hermes"));
        assert_eq!(state["counts"]["served"], json!(1));
        assert_eq!(
            (state["time"].clone(), state["pid"].clone(), state["sourceCommit"].clone()),
            (json!(100), json!(7), json!("abc"))
        );
    }

    #[test]
    fn a_route_keeps_its_last_twenty() {
        let board = Board::default();
        for at in 0..25 {
            board.finish_active(1, "x", json!({"at": at}));
        }
        let state = board.state_json(0.0, 0.0, 0, "");
        let recent = state["agents"]["1"]["recent"].as_array().unwrap();
        assert_eq!((recent.len(), recent[0]["at"].clone()), (20, json!(5)));
    }

    #[test]
    fn failures_are_counted() {
        let board = Board::default();
        board.count_journal_failure();
        let state = board.state_json(0.0, 0.0, 0, "");
        assert_eq!(state["counts"]["journalFailures"], json!(1));
    }

    #[test]
    fn waiting_requests_come_and_go() {
        let board = Board::default();
        board.add_pending(json!({"id": "a"}));
        board.add_pending(json!({"id": "b"}));
        board.remove_pending("a");
        assert_eq!(board.pending_items(), vec![json!({"id": "b"})]);
    }
}
