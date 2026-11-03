//! What a cell's process is at a moment: who holds it and what it was started with, the state behind its lock.

use os::Signals;
use serde_json::{Map, Value, json};
use std::path::PathBuf;
use std::process::Child;

/// Who a process is, while there is one.
#[derive(Debug, Default)]
pub(super) enum Held {
    /// None.
    #[default]
    Nothing,
    /// This scout's child.
    Child(Child),
    /// A process that survived a scout's restart: not this one's child, so it is managed by its pid.
    Adopted(i64),
    /// A process a stop is taking down: the stop holds its handle, and it runs until it is gone.
    Stopping(i64),
}

/// What a process's state is made of.
#[derive(Debug, Default)]
pub(super) struct Inner {
    pub(super) held: Held,
    pub(super) config: Map<String, Value>,
    pub(super) started_at: i64,
    pub(super) last_error: String,
    pub(super) log_path: Option<PathBuf>,
    pub(super) exit_info: Option<Map<String, Value>>,
    /// How it was last launched: argv, the extra environment, the log. A crash is followed by the same launch, also after a scout's restart.
    pub(super) launch: Option<Value>,
}

impl Inner {
    /// Whether its process runs now.
    pub(super) fn is_running(&mut self) -> bool {
        match &mut self.held {
            Held::Child(child) => matches!(child.try_wait(), Ok(None)),
            Held::Adopted(pid) => Signals::alive(*pid),
            Held::Stopping(_) => true,
            Held::Nothing => false,
        }
    }

    /// The row of a process that runs.
    pub(super) fn running_row(&self, pid: i64, now: i64) -> Map<String, Value> {
        let mut out = Map::new();
        out.insert("running".to_string(), json!(true));
        out.insert("pid".to_string(), json!(pid));
        out.insert("startedAt".to_string(), json!(self.started_at));
        out.insert("uptimeSec".to_string(), json!(now - self.started_at));
        out.extend(self.config.iter().filter(|(key, _)| key.as_str() != "cmd").map(|(key, value)| (key.clone(), value.clone())));
        out
    }
}
