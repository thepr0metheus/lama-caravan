//! The scout's `state.json`: what it keeps across restarts.

use crate::log::Log;
use files::AtomicFile;
use serde_json::{Map, Value, json};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard, PoisonError};

/// `state.json` as the document it is: the heartbeat's last outcome, when the scout started, and the `cells` registry the next start
/// takes back. One lock for all who read or write it, and a save that leaves the old file or the new one.
#[derive(Debug)]
pub struct ScoutState {
    path: PathBuf,
    doc: Mutex<Map<String, Value>>,
}

impl ScoutState {
    /// What 1.x kept about the agents on its machine. Nothing reads it now.
    const STALE_1X: [&'static str; 2] = ["assignments", "applyStatus"];

    /// The state at `path`, at `now`. A missing or an unreadable file is an empty one: a bad state is a bad start, not a dead scout.
    pub fn load(path: &Path, now: i64) -> Self {
        // The cells' start requests and keys are in it.
        AtomicFile::narrow(path);
        let read = std::fs::read(path).ok().and_then(|text| serde_json::from_slice::<Value>(&text).ok());
        let mut doc = match read {
            Some(Value::Object(fields)) => fields,
            _ => Map::new(),
        };
        doc.entry("startedAt".to_string()).or_insert_with(|| json!(now));
        doc.entry("heartbeat".to_string()).or_insert_with(|| json!({"state": "pending"}));
        let stale: Vec<&str> = Self::STALE_1X.iter().copied().filter(|key| doc.contains_key(*key)).collect();
        for key in &stale {
            doc.remove(*key);
        }
        let state = Self { path: path.to_path_buf(), doc: Mutex::new(doc) };
        if !stale.is_empty() {
            Log::line(&format!("[state] dropped what 1.x kept about agents: {}", stale.join(", ")));
            state.save(&state.doc());
        }
        state
    }

    fn doc(&self) -> MutexGuard<'_, Map<String, Value>> {
        self.doc.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// Where it is kept: what stands beside it (the saved configs, the engines' logs) is found from here.
    pub fn folder(&self) -> &Path {
        self.path.parent().unwrap_or(Path::new("."))
    }

    /// The file as it is on disk, copied beside it as `<name>.<suffix>` with its own permissions — it holds the cells' start requests:
    /// the way back past a move of what it keeps. Where the copy is.
    pub fn keep_copy(&self, suffix: &str) -> std::io::Result<PathBuf> {
        let name = self.path.file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
        let copy = self.path.with_file_name(format!("{name}.{suffix}"));
        std::fs::copy(&self.path, &copy)?;
        Ok(copy)
    }

    /// Reads under the lock.
    pub fn read<T>(&self, reader: impl FnOnce(&Map<String, Value>) -> T) -> T {
        reader(&self.doc())
    }

    /// Changes under the lock, and saves.
    pub fn change<T>(&self, change: impl FnOnce(&mut Map<String, Value>) -> T) -> T {
        let mut doc = self.doc();
        let out = change(&mut doc);
        self.save(&doc);
        out
    }

    /// The top-level value of `key`.
    pub fn get(&self, key: &str) -> Option<Value> {
        self.read(|doc| doc.get(key).cloned())
    }

    /// 0600: the cells' start requests and launches are in it, and with them their keys. A disk that refuses is said, and the run goes on.
    fn save(&self, doc: &Map<String, Value>) {
        let written = serde_json::to_string_pretty(doc)
            .map_err(std::io::Error::other)
            .and_then(|text| AtomicFile::write_private(&self.path, text.as_bytes()));
        if let Err(error) = written {
            Log::line(&format!("[state] not saved: {error}"));
        }
    }
}
