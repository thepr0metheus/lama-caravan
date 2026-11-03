//! What is in the cache's folder that is not this scout's: counted and shown, deleted only when the operator asks with the figure he was shown.

use crate::errors::AppError;
use crate::log::{Log, Thousands};
use crate::models::files::{Resolved, Walk};
use crate::models::keeper::CacheKeeper;
use rules::Coerce;
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;
use std::sync::PoisonError;

impl CacheKeeper {
    /// (file, bytes) for every file of the cache folder that this scout did not download. Hidden names (the scouts' scratch, a library's own cache) and logs are not models and are left out; a link is counted as a link.
    pub(super) fn foreign_files(&self) -> Vec<(PathBuf, u64)> {
        const NOT_MODELS: [&str; 3] = [".log", ".tmp", ".part"];
        let cache = self.models.cache_dir();
        let mine = self.models.downloaded.names();
        let mut found = Vec::new();
        let mut todo = vec![cache.clone()];
        while let Some(folder) = todo.pop() {
            let Ok(entries) = fs::read_dir(&folder) else {
                continue;
            };
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().into_owned();
                let path = entry.path();
                if name.starts_with('.') {
                    continue;
                }
                if entry.file_type().is_ok_and(|kind| kind.is_dir()) {
                    todo.push(path);
                } else if !path.is_dir() && !NOT_MODELS.iter().any(|ending| name.ends_with(ending)) {
                    let rel = path.strip_prefix(&cache).map_or_else(|_| name.clone(), |rel| rel.to_string_lossy().into_owned());
                    if let Some(meta) = entry.metadata().ok().filter(|_| !crate::models::DownloadedFiles::covers(&mine, &rel)) {
                        found.push((path, meta.len()));
                    }
                }
            }
        }
        found
    }

    /// Deletes the foreign files: only when the figure the operator was shown is still the figure (409 otherwise: something came or went since he looked), and never what a cell holds or is starting on.
    pub fn delete_foreign(&self, expect_bytes: Option<&Value>) -> Result<Value, AppError> {
        self.models.relocation.refuse_while_moving()?;
        let expect = expect_bytes
            .and_then(Coerce::int)
            .ok_or_else(|| AppError::new("expectBytes is required: the size the operator was shown"))?;
        let found = self.foreign_files();
        let total: u64 = found.iter().map(|(_, size)| *size).sum();
        if u64::try_from(expect).ok() != Some(total) {
            return Err(AppError::with_status(
                format!(
                    "the cache changed since it was shown: {} bytes of files this scout did not download, not {} — nothing was deleted",
                    Thousands::of(total as i64),
                    Thousands::of(expect)
                ),
                409,
            ));
        }
        let _one_at_a_time = self.busy.lock().unwrap_or_else(PoisonError::into_inner);
        let protected = self.protected();
        let (mut removed, mut freed) = (0u64, 0u64);
        for (path, size) in &found {
            if !protected.contains(&Resolved::of(path)) && !self.models.is_flying(path) && fs::remove_file(path).is_ok() {
                removed += 1;
                freed += size;
            }
        }
        self.prune_empty();
        self.forget_figures();
        if removed != 0 {
            Log::line(&format!(
                "[llama-node] cache: removed {removed} file(s) this scout did not download, freed {} bytes",
                Thousands::of(freed as i64)
            ));
        }
        Ok(json!({"removed": removed, "freedBytes": freed}))
    }

    /// The folders a deletion left empty, bottom up; the cache folder itself and the hidden ones stay.
    pub(super) fn prune_empty(&self) {
        let cache = self.models.cache_dir();
        let mut folders: Vec<PathBuf> =
            Walk::entries(&cache).into_iter().filter(|path| path.symlink_metadata().is_ok_and(|meta| meta.is_dir())).collect();
        folders.sort_by_key(|path| std::cmp::Reverse(path.components().count()));
        for folder in folders {
            let rel = folder.strip_prefix(&cache).unwrap_or(&folder);
            if !rel.components().any(|part| part.as_os_str().to_string_lossy().starts_with('.')) {
                // Only an empty folder goes: the one that holds anything stays.
                drop(fs::remove_dir(&folder));
            }
        }
    }
}
