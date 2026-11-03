//! The folders the board chose for this machine: where the model cache is, and where the cells keep what they make from their models.

use crate::state::ScoutState;
use serde_json::json;
use std::path::{Path, PathBuf};
use std::sync::Arc;

/// A folder the board chose. It lives in `state.json`, the scout's own memory: the board changes it over HTTP, and `config.json` stays the file the operator wrote.
pub struct ChosenFolder {
    state: Arc<ScoutState>,
    key: &'static str,
}

impl ChosenFolder {
    /// The folder the board chose, when it chose one.
    pub fn value(&self) -> Option<PathBuf> {
        let raw = self.state.get(self.key)?;
        raw.as_str().filter(|path| path.starts_with('/')).map(PathBuf::from)
    }

    /// Chooses `path`.
    pub fn set(&self, path: &Path) {
        self.state.change(|doc| doc.insert(self.key.to_string(), json!(path.display().to_string())));
    }

    /// Forgets the choice: the folder is where it lies by itself again.
    pub fn forget(&self) {
        self.state.change(|doc| doc.remove(self.key));
    }
}

/// The folders the board chose: where the model cache is, and where the cells keep what they make from their models. The owner, 2026-11-03: Strata writes its pack at a start with the cache
/// on or off, and he wants it on a disk of his choosing, not on the one the cache lies on.
pub struct Folders {
    /// Where the cache is.
    pub cache: ChosenFolder,
    /// Where the cells keep what they make.
    pub work: ChosenFolder,
}

impl Folders {
    /// The folders kept in this state.
    pub fn new(state: &Arc<ScoutState>) -> Self {
        Self {
            cache: ChosenFolder { state: Arc::clone(state), key: "cacheDir" },
            work: ChosenFolder { state: Arc::clone(state), key: "workDir" },
        }
    }
}
