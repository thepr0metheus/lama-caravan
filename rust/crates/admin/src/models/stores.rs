//! Model stores: the controller's own models folder and the libraries beside it. A store's look is a child process: a share that hangs must not hang a page.

use super::store_probe::StoreProbe;
use crate::app::App;
use net::Randomness;
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::sync::{Mutex, PoisonError};

mod mount;
pub use mount::MountFacts;
pub use mount::StoreStatus;

mod edit;
#[cfg(test)]
mod tests;

/// A store that cannot be added or removed, with a reason the page can act on.
pub struct StoreRefused {
    /// What is said.
    pub error: AppError,
    /// The word the page acts on.
    pub code: String,
}

impl StoreRefused {
    /// A refusal.
    pub fn refused(message: impl Into<String>, code: &str, status: u16) -> Self {
        Self { error: AppError::with_status(message, status), code: code.to_string() }
    }
}

/// One place models live.
#[derive(Debug, Clone)]
pub struct ModelStore {
    /// Its id.
    pub id: String,
    /// Its name.
    pub name: String,
    /// Its folder.
    pub path: String,
    /// "local" or "library".
    pub role: &'static str,
    /// Whether it is the controller's own.
    pub builtin: bool,
}

impl ModelStore {
    fn to_json(&self) -> Map<String, Value> {
        let row = json!({"id": self.id, "name": self.name, "path": self.path, "role": self.role, "builtin": self.builtin});
        Coerce::fields(&row)
    }
}

/// A short memory of how each store looked.
#[derive(Default)]
pub struct StoreMemory {
    cache: Mutex<BTreeMap<String, (String, StoreStatus, f64)>>,
    refreshing: Mutex<bool>,
    probe: StoreProbe,
}

/// The stores this controller knows.
pub struct StoreRegistry<'app> {
    app: &'app App,
}

impl<'app> StoreRegistry<'app> {
    /// The id of this host's own folder of models.
    pub const LOCAL_ID: &'static str = "local";
    const TTL: f64 = 15.0;

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn memory(&self) -> &StoreMemory {
        &self.app.store_memory
    }

    fn local(&self) -> String {
        self.app.models_dir().to_string_lossy().into_owned()
    }

    fn saved(&self) -> Vec<Value> {
        self.app.admin.read(|doc| {
            doc.get("modelStores")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter(|row| {
                    row.is_object()
                        && !Coerce::stripped(row.get("id")).is_empty()
                        && !Coerce::stripped(row.get("path")).is_empty()
                })
                .cloned()
                .collect()
        })
    }

    fn put_saved(&self, rows: Vec<Value>) {
        self.app.admin.saving(|doc| doc.insert("modelStores".to_string(), Value::Array(rows)));
    }

    /// All of them, the controller's own first.
    pub fn stores(&self) -> Vec<ModelStore> {
        let mut out = vec![ModelStore {
            id: Self::LOCAL_ID.to_string(),
            name: String::new(),
            path: self.local(),
            role: "local",
            builtin: true,
        }];
        out.extend(self.saved().iter().map(|row| ModelStore {
            id: Coerce::text(row.get("id")),
            name: Coerce::text(row.get("name")),
            path: Coerce::text(row.get("path")),
            role: "library",
            builtin: false,
        }));
        out
    }

    fn stale(cache: &BTreeMap<String, (String, StoreStatus, f64)>, store: &ModelStore, now: f64) -> bool {
        cache.get(&store.id).is_none_or(|(path, _, at)| *path != store.path || now - at >= Self::TTL)
    }

    fn cache(&self) -> std::sync::MutexGuard<'_, BTreeMap<String, (String, StoreStatus, f64)>> {
        self.memory().cache.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// Every store with its latest measurement.
    pub fn statuses(&self, force: bool) -> Vec<Value> {
        let stores = self.stores();
        let now = self.app.now();
        let stale: Vec<ModelStore> = {
            let cache = self.cache();
            stores.iter().filter(|store| force || Self::stale(&cache, store, now)).cloned().collect()
        };
        self.measure(&stale, now);
        let cache = self.cache();
        stores
            .iter()
            .map(|store| {
                let mut row = store.to_json();
                let status = cache.get(&store.id).map_or_else(
                    || StoreStatus::new("unknown", "not measured yet", 0).to_json(),
                    |(_, status, _)| status.to_json(),
                );
                row.extend(status);
                Value::Object(row)
            })
            .collect()
    }

    fn measure(&self, stale: &[ModelStore], now: f64) {
        const AT_ONCE: usize = 4;
        for group in stale.chunks(AT_ONCE) {
            let probe = &self.memory().probe;
            let looks: Vec<Value> = std::thread::scope(|scope| {
                let handles: Vec<_> =
                    group.iter().map(|store| scope.spawn(move || probe.look(&store.path, store.role == "library"))).collect();
                handles
                    .into_iter()
                    .map(|handle| handle.join().unwrap_or_else(|_| json!({"ok": false, "error": "the probe failed"})))
                    .collect()
            });
            for (store, look) in group.iter().zip(&looks) {
                let mut status = StoreStatus::judge(store, look, now.trunc() as i64);
                if status.state != "ok" {
                    status.measured.insert("mount".to_string(), MountFacts::at(&store.path));
                }
                self.cache().insert(store.id.clone(), (store.path.clone(), status, now));
            }
        }
    }

    /// What each library holds, its GGUF files and its model folders, for the tree on /models, the picker and the start path. `wait`: measure now; otherwise a stale look is refreshed behind this answer.
    pub fn library_files(&self, force: bool, wait: bool) -> Vec<Value> {
        if wait {
            self.statuses(force);
        } else {
            self.refresh_behind();
        }
        let now = self.app.now();
        let mut rows = Vec::new();
        for store in self.stores().iter().filter(|store| store.role == "library") {
            let hit = self.cache().get(&store.id).filter(|(path, _, _)| *path == store.path).map(|(_, status, _)| status.clone());
            let status = hit.unwrap_or_else(|| StoreStatus::new("unknown", "not measured yet", 0));
            let age = |mtime: f64| ((now - mtime).max(0.0) / 86400.0).floor() as i64;
            let mut found: Vec<Value> = Vec::new();
            for row in status.measured.get("entries").and_then(Value::as_array).into_iter().flatten() {
                // absent-ok: a listing row with no time reads as old.
                let mtime = row.get(2).and_then(Value::as_f64).unwrap_or_default();
                found.push(json!({"path": row.get(0), "size": row.get(1), "ageDays": age(mtime), "mtime": mtime.trunc() as i64}));
            }
            for row in status.measured.get("dirs").and_then(Value::as_array).into_iter().flatten() {
                // absent-ok: a listing row with no time reads as old.
                let mtime = row.get(3).and_then(Value::as_f64).unwrap_or_default();
                found.push(json!({"path": row.get(0), "kind": row.get(1), "size": row.get(2), "ageDays": age(mtime), "mtime": mtime.trunc() as i64}));
            }
            found.sort_by_key(|row| Coerce::text(row.get("path")));
            let count = |key: &str| Coerce::i64_or_zero(status.measured.get(key));
            rows.push(json!({"id": store.id, "name": if store.name.is_empty() { &store.id } else { &store.name }, "state": status.state, "path": store.path, "files": found, "more": count("entriesMore") + count("dirsMore")}));
        }
        rows
    }

    /// Measures what is stale on a thread of its own: one at a time.
    fn refresh_behind(&self) {
        let now = self.app.now();
        let stores = self.stores();
        {
            let mut refreshing = self.memory().refreshing.lock().unwrap_or_else(PoisonError::into_inner);
            let cache = self.cache();
            if *refreshing || !stores.iter().any(|store| Self::stale(&cache, store, now)) {
                return;
            }
            *refreshing = true;
        }
        let Some(app) = self.app.shared() else {
            *self.memory().refreshing.lock().unwrap_or_else(PoisonError::into_inner) = false;
            return;
        };
        let started = std::thread::Builder::new().name("store-refresh".to_string()).spawn(move || {
            let registry = StoreRegistry::of(&app);
            registry.statuses(false);
            *registry.memory().refreshing.lock().unwrap_or_else(PoisonError::into_inner) = false;
        });
        if started.is_err() {
            *self.memory().refreshing.lock().unwrap_or_else(PoisonError::into_inner) = false;
        }
    }
}

/// `os.path.normpath` of an absolute path.
pub struct PathWord;

impl PathWord {
    /// The path with `.`, `..` and doubled slashes gone.
    pub fn normal(path: &str) -> String {
        let mut parts: Vec<&str> = Vec::new();
        for part in path.split('/') {
            match part {
                "" | "." => {}
                ".." => {
                    parts.pop();
                }
                other => parts.push(other),
            }
        }
        format!("/{}", parts.join("/"))
    }
}
