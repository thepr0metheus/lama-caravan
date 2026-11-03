//! What this process knows about each output's health a pool's rows read.
//!
//! A verdict comes from traffic. A fresh "dead" passes the row over at once; an expired one is re-checked by the next request. A 400 is that
//! request's problem: the output answered, and it must not divert five minutes of everyone's traffic.

use rules::{Coerce, UpstreamFailure};
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::sync::{Mutex, PoisonError};

/// One verdict.
#[derive(Debug, Clone, PartialEq)]
struct Verdict {
    dead: bool,
    status: Option<u16>,
    kind: String,
    message: String,
    checked_at: f64,
    last_ok_at: Option<f64>,
}

/// Per-output verdicts with an expiry.
#[derive(Debug, Default)]
pub struct OutputHealth {
    rows: Mutex<BTreeMap<String, Verdict>>,
}

impl OutputHealth {
    /// How long a verdict holds: the five minutes of idle.
    const HOLDS_SECONDS: f64 = 300.0;
    const MESSAGE_LETTERS: usize = 200;

    fn put(&self, output: &str, mut verdict: Verdict) {
        if output.is_empty() {
            return;
        }
        let mut rows = self.rows.lock().unwrap_or_else(PoisonError::into_inner);
        if verdict.dead {
            // A failure does not erase when the output last answered.
            verdict.last_ok_at = rows.get(output).and_then(|row| row.last_ok_at);
        }
        rows.insert(output.to_string(), verdict);
    }

    /// The output answered usefully: alive, from this moment.
    pub fn note_ok(&self, output: &str, now: f64) {
        self.put(
            output,
            Verdict {
                dead: false,
                status: None,
                kind: String::new(),
                message: String::new(),
                checked_at: now,
                last_ok_at: Some(now),
            },
        );
    }

    /// The output could not serve: dead, from this moment, with the reason kept.
    pub fn note_error(&self, output: &str, status: Option<u16>, kind: &str, message: &str, now: f64) {
        let kind = if kind.is_empty() {
            status.map_or_else(|| "error".to_string(), |status| format!("http {status}"))
        } else {
            kind.to_string()
        };
        let message = Coerce::first_letters(message, Self::MESSAGE_LETTERS).to_string();
        self.put(output, Verdict { dead: true, status, kind, message, checked_at: now, last_ok_at: None });
    }

    /// An HTTP answer as a verdict: a request-specific 4xx is alive.
    pub fn note_status(&self, output: &str, status: u16, message: &str, now: f64) {
        if UpstreamFailure::is_dead_status(status) {
            self.note_error(output, Some(status), "", message, now);
        } else {
            self.note_ok(output, now);
        }
    }

    /// Dead means a fresh error verdict; an expired one is only a memory.
    pub fn is_dead(&self, output: &str, now: f64) -> bool {
        let rows = self.rows.lock().unwrap_or_else(PoisonError::into_inner);
        rows.get(output).is_some_and(|row| row.dead && now - row.checked_at < Self::HOLDS_SECONDS)
    }

    /// Every verdict, for the state file: `OutputHealth.snapshot`.
    pub fn snapshot(&self, now: f64) -> Value {
        let rows = self.rows.lock().unwrap_or_else(PoisonError::into_inner);
        let mut out = Map::new();
        for (output, row) in rows.iter() {
            let age = (now - row.checked_at).max(0.0) as i64;
            let holds = Self::HOLDS_SECONDS as i64;
            out.insert(
                output.clone(),
                json!({
                    "state": if row.dead { "error" } else { "ok" },
                    "status": row.status,
                    "kind": row.kind,
                    "message": row.message,
                    "checkedAt": row.checked_at,
                    "lastOkAt": row.last_ok_at,
                    "source": "traffic",
                    "ageSec": age,
                    "fresh": age < holds,
                    "retryInSec": (holds - age).max(0),
                }),
            );
        }
        Value::Object(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_fresh_failure_is_dead_and_an_old_one_is_a_memory() {
        let health = OutputHealth::default();
        assert!(!health.is_dead("a", 100.0));
        health.note_status("a", 500, "words", 100.0);
        assert!(health.is_dead("a", 100.0));
        assert!(health.is_dead("a", 399.9));
        assert!(!health.is_dead("a", 400.0));
    }

    #[test]
    fn a_request_s_own_refusal_counts_as_alive() {
        let health = OutputHealth::default();
        health.note_status("a", 500, "", 100.0);
        health.note_status("a", 400, "too long", 101.0);
        assert!(!health.is_dead("a", 101.0));
        for dead in [401, 402, 403, 404, 408, 429, 500, 502, 503, 504] {
            health.note_status("a", dead, "", 102.0);
            assert!(health.is_dead("a", 102.0), "{dead}");
        }
    }

    #[test]
    fn a_failure_keeps_when_the_output_last_answered() {
        let health = OutputHealth::default();
        health.note_ok("a", 100.0);
        health.note_error("a", None, "connect", "refused", 150.0);
        let said = health.snapshot(160.0);
        assert_eq!(said["a"]["lastOkAt"], json!(100.0));
        assert_eq!(said["a"]["state"], json!("error"));
        assert_eq!(said["a"]["kind"], json!("connect"));
        assert_eq!(said["a"]["ageSec"], json!(10));
        assert_eq!(said["a"]["retryInSec"], json!(290));
        assert_eq!(said["a"]["fresh"], json!(true));
        health.note_error("", None, "connect", "", 170.0);
        assert_eq!(health.snapshot(170.0).as_object().unwrap().len(), 1, "no output, no verdict");
    }

    #[test]
    fn a_status_names_its_kind_when_nothing_else_does() {
        let health = OutputHealth::default();
        health.note_status("a", 503, &"x".repeat(300), 100.0);
        let said = health.snapshot(100.0);
        assert_eq!(said["a"]["kind"], json!("http 503"));
        assert_eq!(said["a"]["message"].as_str().unwrap().len(), 200);
        health.note_error("b", None, "", "", 100.0);
        assert_eq!(health.snapshot(100.0)["b"]["kind"], json!("error"));
    }
}
