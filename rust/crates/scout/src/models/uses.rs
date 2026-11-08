//! A shelf's settings, and its log of what was started.

use crate::errors::AppError;
use crate::state::ScoutState;
use os::clock::Clock;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::sync::Arc;

/// The setting: how many of the last started models the cache keeps.
pub struct CacheKeep {
    state: Arc<ScoutState>,
}

impl CacheKeep {
    /// The setting in this state.
    pub fn new(state: Arc<ScoutState>) -> Self {
        Self { state }
    }

    const MIN: i64 = 1;
    const MAX: i64 = 5;
    const DEFAULT: i64 = 1;
    const KEY: &'static str = "cacheKeep";

    fn sound(raw: &Value) -> Option<i64> {
        raw.as_i64().filter(|count| (Self::MIN..=Self::MAX).contains(count))
    }

    /// How many: the operator's, or one until he says.
    pub fn value(&self) -> i64 {
        self.state.get(Self::KEY).as_ref().and_then(Self::sound).unwrap_or(Self::DEFAULT)
    }

    /// Keep `raw` models. A whole number from 1 to 5: a string, a bool, 0 and 6 are refused, not rounded into one.
    pub fn set(&self, raw: &Value) -> Result<i64, AppError> {
        let keep = Self::sound(raw)
            .ok_or_else(|| AppError::new(format!("keep must be a whole number from {} to {}", Self::MIN, Self::MAX)))?;
        self.state.change(|doc| doc.insert(Self::KEY.to_string(), json!(keep)));
        Ok(keep)
    }
}

/// The setting: how much a shelf's models may take in all, in bytes. The model cache's is `None` until the operator chooses — a size nobody chose is not made up for him; the folder for Strata's
/// files has one from the start, the owner's 300 GB (shelf.rs).
pub struct CacheBudget {
    state: Arc<ScoutState>,
    key: &'static str,
    default: Option<i64>,
}

impl CacheBudget {
    /// The setting kept under `key` in this state, `default` until the operator chooses.
    pub fn new(state: Arc<ScoutState>, key: &'static str, default: Option<i64>) -> Self {
        Self { state, key, default }
    }

    /// A gibibyte at least: a smaller budget keeps no model a cell could run.
    const MIN: i64 = 1 << 30;
    /// A bound against a typo, not a rule.
    const MAX: i64 = 1 << 50;

    fn sound(raw: &Value) -> Option<i64> {
        raw.as_i64().filter(|bytes| (Self::MIN..=Self::MAX).contains(bytes))
    }

    /// The budget the operator chose, else the shelf's own; `None` for a cache nobody chose one for.
    pub fn value(&self) -> Option<i64> {
        self.chosen().or(self.default)
    }

    /// The budget the operator chose, when he did.
    pub fn chosen(&self) -> Option<i64> {
        self.state.get(self.key).as_ref().and_then(Self::sound)
    }

    /// Keep at most `raw` bytes of models; `null` takes the operator's budget off, and the shelf's own rules again.
    pub fn set(&self, raw: &Value) -> Result<Option<i64>, AppError> {
        if raw.is_null() {
            self.state.change(|doc| doc.remove(self.key));
            return Ok(self.default);
        }
        let bytes = Self::sound(raw).ok_or_else(|| {
            AppError::new(format!(
                "budgetBytes must be a whole number of bytes from {} (1 GiB) to {}, or null",
                Self::MIN,
                Self::MAX
            ))
        })?;
        self.state.change(|doc| doc.insert(self.key.to_string(), json!(bytes)));
        Ok(Some(bytes))
    }
}

/// What was started, newest first: for each model its files as the controller named them (the first is the model itself), the cell that started it, when, and whether the start got as far as a
/// running process.
pub struct ModelUses {
    state: Arc<ScoutState>,
    clock: Arc<dyn Clock>,
    key: &'static str,
}

impl ModelUses {
    /// The log kept under `key` in this state: each shelf keeps its own.
    pub fn new(state: Arc<ScoutState>, clock: Arc<dyn Clock>, key: &'static str) -> Self {
        Self { state, clock, key }
    }

    const LIMIT: usize = 20;

    fn sound(entry: &Value) -> bool {
        let files = entry.get("files").and_then(Value::as_array);
        files
            .is_some_and(|files| !files.is_empty() && files.iter().all(|file| file.as_str().is_some_and(|name| !name.is_empty())))
    }

    fn sound_of(doc: &Map<String, Value>, key: &str) -> Vec<Value> {
        doc.get(key).and_then(Value::as_array).into_iter().flatten().filter(|entry| Self::sound(entry)).cloned().collect()
    }

    fn first_file(entry: &Value) -> Option<&str> {
        entry.get("files").and_then(|files| files.get(0)).and_then(Value::as_str)
    }

    /// The cell an entry was started by.
    pub fn cell_of(entry: &Value) -> Option<&str> {
        entry.get("cell").and_then(Value::as_str)
    }

    /// The entries that read, newest first.
    pub fn entries(&self) -> Vec<Value> {
        self.state.read(|doc| Self::sound_of(doc, self.key))
    }

    /// A start asks for these files. The entry stands at the front from this moment, not `ok` yet, except that a model which has run before keeps the word it earned: a start that fails does not
    /// unmake the model that worked.
    pub fn begin(&self, cell: &str, files: &[String]) {
        let names: Vec<&str> = files.iter().map(|file| Coerce::strip(file)).filter(|name| !name.is_empty()).collect();
        let Some(first) = names.first().copied() else {
            return;
        };
        let at = self.clock.epoch() as i64;
        self.state.change(|doc| {
            let current = Self::sound_of(doc, self.key);
            let ran = current
                .iter()
                .find(|entry| Self::first_file(entry) == Some(first))
                .is_some_and(|entry| Coerce::truthy(entry.get("ok")));
            let mut kept = vec![json!({"files": names, "cell": cell, "at": at, "ok": ran})];
            kept.extend(current.into_iter().filter(|entry| Self::first_file(entry) != Some(first)));
            kept.truncate(Self::LIMIT);
            doc.insert(self.key.to_string(), Value::Array(kept));
        });
    }

    /// The start of `cell` got as far as a running process: its newest entry is a model that ran.
    pub fn commit(&self, cell: &str) {
        self.state.change(|doc| {
            let mut entries = doc.get_mut(self.key).and_then(Value::as_array_mut);
            let list = entries.iter_mut().flat_map(|list| list.iter_mut());
            if let Some(Value::Object(entry)) =
                list.filter(|entry| Self::sound(entry)).find(|entry| Self::cell_of(entry) == Some(cell))
            {
                entry.insert("ok".to_string(), json!(true));
            }
        });
    }

    /// The newest `count` models that ran.
    pub fn newest(&self, count: usize) -> Vec<Value> {
        self.entries().into_iter().filter(|entry| Coerce::truthy(entry.get("ok"))).take(count).collect()
    }
}
