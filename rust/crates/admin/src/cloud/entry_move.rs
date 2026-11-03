//! The move to clients without sets, as the board shows it once (the owner, 2026-10-27).

use crate::app::App;
use crate::store::admin::AdminStore;
use rules::{Coerce, EntryModels};
use serde_json::{Value, json};

/// The record of the move in the board's state: what the clients could call before, and what they call now.
pub struct EntryMove<'app> {
    app: &'app App,
}

impl<'app> EntryMove<'app> {
    const KEY: &'static str = "entryMove";

    /// The record of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// What the move answered kept, not yet seen.
    pub fn record(&self, moved: Option<&Value>) {
        let Some(moved) = moved.filter(|moved| moved.is_object()) else {
            return;
        };
        let list = |key: &str| moved.get(key).filter(|said| said.is_array()).cloned().unwrap_or_else(|| json!([]));
        let kept = json!({"clients": list("clients"), "sets": list("sets"), "seen": false});
        self.app.admin.saving(|doc| {
            AdminStore::topology(doc).insert(Self::KEY.to_string(), kept);
        });
    }

    /// The operator answered the window: it is not shown again. Whether there was a record to answer.
    pub fn seen(&self) -> bool {
        self.app.admin.saving(|doc| {
            let kept = AdminStore::topology(doc).get_mut(Self::KEY).filter(|kept| kept.is_object());
            let Some(kept) = kept else {
                return false;
            };
            Coerce::put(kept, "seen", json!(true));
            true
        })
    }

    /// What the board's window of the move shows; `None` with no record, or one answered.
    pub fn state(&self, entry_models: &EntryModels) -> Option<Value> {
        let kept = self.app.admin.read(|doc| doc.get("topology").and_then(|topology| topology.get(Self::KEY)).cloned())?;
        if !kept.is_object() || Coerce::truthy(kept.get("seen")) {
            return None;
        }
        let objects = |key: &str| -> Vec<Value> {
            kept.get(key).and_then(Value::as_array).into_iter().flatten().filter(|row| row.is_object()).cloned().collect()
        };
        let sees = entry_models.models(&rules::ClientDeny::default()).len();
        Some(json!({"clients": objects("clients"), "sets": objects("sets"), "sees": sees, "twins": entry_models.twins()}))
    }
}
