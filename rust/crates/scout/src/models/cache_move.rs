//! The model cache moved to another folder, by the operator's word. The owner, 2026-10-26: an HDD, not the SSD's writes; 2026-11-03: the files either move with it or go, and a folder removed takes
//! its files with it, the cache going back to the folder it lies in by itself.

use super::keeper::CacheKeeper;
use super::relocate::FileMove;
use crate::errors::AppError;
use crate::log::{Log, Thousands};
use crate::models::fetcher::ModelFetcher;
use crate::models::files::{Resolved, Walk};
use rules::Coerce;
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::path::Path;
use std::sync::{Arc, PoisonError};

/// What a move does with the files of the folder it leaves.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Carry {
    /// They go with it.
    Move,
    /// They are deleted.
    Delete,
}

impl Carry {
    /// The operator's word: "move" or "delete"; none is "delete", as every move was before there was a choice. Any other word is refused, not taken for one of them.
    pub fn of(raw: &Value) -> Result<Self, AppError> {
        match raw.as_str() {
            Some("move") => Ok(Self::Move),
            Some("delete") => Ok(Self::Delete),
            None if raw.is_null() => Ok(Self::Delete),
            _ => Err(AppError::new(format!("how must be \"move\" or \"delete\", not {raw}"))),
        }
    }
}

impl CacheKeeper {
    /// Moves the cache to the folder `raw` names, or back to the folder it lies in by itself when `raw` names none. `how`, "move": the scout's own files go with it, on a thread of their own
    /// (relocate.rs); "delete": they are deleted, as every model of it is the controller's copy and a start brings its model into the new folder by itself. Not while a start is bringing its files
    /// (409, the cells named); a running cell has its weights loaded, and its open files outlive their names.
    pub fn move_to(&self, raw: &Value, how: &Value) -> Result<Value, AppError> {
        let carry = Carry::of(how)?;
        let text = Coerce::stripped(Some(raw).filter(|raw| Coerce::truthy(Some(*raw))));
        let back = text.is_empty();
        if back && self.models.folders.cache.value().is_none() {
            return Err(AppError::new("the cache lies in its own folder already: name the folder it is to be in"));
        }
        let new = if back { self.models.cache_dir_by_itself() } else { ModelFetcher::expanded(&text) };
        if !new.is_absolute() {
            return Err(AppError::new(format!("the cache folder must be an absolute path: {text}")));
        }
        let (new, old) = (Resolved::of(&new), Resolved::of(&self.models.cache_dir()));
        if new == old {
            return Err(AppError::new(format!("the cache is in {} already", new.display())));
        }
        if new.starts_with(&old) || old.starts_with(&new) {
            return Err(AppError::new(format!(
                "the new folder may not lie inside the old one or hold it: {} and {}",
                new.display(),
                old.display()
            )));
        }
        self.refuse_over_work(&new)?;
        let _one_at_a_time = self.busy.lock().unwrap_or_else(PoisonError::into_inner);
        self.models.relocation.refuse_while_moving()?;
        self.refuse_while_loading("the cache does not move")?;
        // Made and written in only once nothing refuses: a refused move left an empty folder on the disk it named (2026-11-03).
        Self::can_write_in(&new, "the cache")?;
        if carry == Carry::Move {
            let (models, target) = (Arc::clone(&self.models), new.clone());
            let switch = Box::new(move || if back { models.folders.cache.forget() } else { models.choose_folder(&target) });
            let files = FileMove { from: old, to: new, names: self.own_names() };
            return self.models.start_move(files, switch);
        }
        // A running cell's scratch stays in the old folder: the cell writes there.
        let made = self.models.clear_scratches(&self.cells.live_cells());
        let result = Self::with_made(&self.models.clear(), made);
        self.prune_empty();
        if back {
            self.models.folders.cache.forget();
        } else {
            self.models.choose_folder(&new);
        }
        self.forget_figures();
        Log::line(&format!(
            "[llama-node] the cache moved from {} to {}: removed {} file(s) this scout downloaded there, freed {} bytes",
            old.display(),
            new.display(),
            Coerce::text(result.get("removed")),
            // absent-ok: the clearing says the two together.
            Thousands::of(result.get("freedBytes").and_then(Value::as_i64).unwrap_or(0))
        ));
        Ok(json!({"dir": new.display().to_string(), "removed": result.get("removed"), "freedBytes": result.get("freedBytes")}))
    }

    /// Refuses while a start is bringing its model: `what` does not happen then, and the cells are named.
    pub(super) fn refuse_while_loading(&self, what: &str) -> Result<(), AppError> {
        let loading = self.cells.loading_cells();
        if loading.is_empty() {
            return Ok(());
        }
        let named = self.cells.called(&loading);
        Err(AppError::with_status(
            format!("{what} while a cell is bringing its model: {} — try again when it runs", named.join(", ")),
            409,
        ))
    }

    /// A shelf's own files, as names inside its folder: what the record names (a folder by its files), the record itself, and what its stopped cells made. A file the record names and the disk lacks
    /// is no file to move.
    pub(super) fn own_names(&self) -> Vec<String> {
        let cache = self.models.cache_dir();
        let mut names = BTreeSet::new();
        let mut take = |path: &Path| {
            if let Ok(rel) = path.strip_prefix(&cache) {
                names.insert(rel.to_string_lossy().into_owned());
            }
        };
        for path in self.models.downloaded.paths() {
            match path.symlink_metadata() {
                Ok(meta) if meta.is_dir() => Walk::files_with_sizes(&path).iter().for_each(|(file, _)| take(file)),
                Ok(_) => take(&path),
                Err(_) => {}
            }
        }
        let record = self.models.downloaded.file();
        if record.is_file() {
            take(&record);
        }
        let live = self.cells.live_cells();
        for (_, folder) in self.models.scratch_folders().into_iter().filter(|(cell, _)| !live.contains(cell)) {
            Walk::files_with_sizes(&folder).iter().for_each(|(file, _)| take(file));
        }
        names.into_iter().collect()
    }
}
