//! The folder for Strata's files, the second shelf (shelf.rs): the copies of the models of the cells that need a fast disk, and what those cells make from them. The owner, 2026-11-03: Strata writes
//! a pack of about 2.3 GB at a start whether the cache keeps copies or not, and he wants it on a disk of his choosing; no Strata start until he chose it; a folder that moves takes its files with it
//! or deletes them, as he says; and the models stay there after a stop, up to a size he chooses, so that the disk is not written again at every start.

use super::cache_move::Carry;
use super::relocate::FileMove;
use crate::errors::AppError;
use crate::log::{Log, Thousands};
use crate::models::fetcher::ModelFetcher;
use crate::models::files::Resolved;
use crate::models::keeper::CacheKeeper;
use os::Disk;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, PoisonError};

impl CacheKeeper {
    /// The folder moved to the folder `raw` names, or forgotten when it names none: then a Strata cell does not start. `how`, "move": the copies and what the stopped cells made go with it, on a
    /// thread of their own (relocate.rs); "delete", and always when the folder is forgotten: they are deleted — a copy is the controller's file, and a start makes the rest again. Not while a cell is
    /// bringing its model, nor while one that runs keeps its files there: it reads and writes there, and they would outlive the move unseen (409, the cells named).
    pub fn set_work(&self, raw: &Value, how: &Value) -> Result<Value, AppError> {
        let carry = Carry::of(how)?;
        let text = Coerce::stripped(Some(raw).filter(|raw| Coerce::truthy(Some(*raw))));
        let chosen = if text.is_empty() { None } else { Some(self.work_folder_of(&text)?) };
        let now = self.models.folders.work.value();
        let named = self.models.shelf.named;
        if chosen.is_none() && now.is_none() {
            return Err(AppError::new(format!("no folder is chosen for {named}: name the folder it is to be")));
        }
        if chosen.is_some() && chosen.as_deref().map(Resolved::of) == now.as_deref().map(Resolved::of) {
            return Err(AppError::new(format!("{named} is in {text} already")));
        }
        let _one_at_a_time = self.busy.lock().unwrap_or_else(PoisonError::into_inner);
        self.models.relocation.refuse_while_moving()?;
        self.refuse_while_loading(&format!("{named} does not move"))?;
        let live = self.cells.live_cells();
        let keeping: std::collections::BTreeSet<String> =
            live.iter().filter(|cell| !self.models.scratches_of(cell).is_empty()).cloned().collect();
        let mut busy = self.cells.called(&keeping);
        if busy.is_empty() && self.cells.held_files().iter().any(|file| self.models.in_cache(Path::new(file))) {
            busy.push("a cell that reads its model there".to_string());
        }
        if !busy.is_empty() {
            let words = format!("{named} does not move while a cell keeps its files there: {} — stop it first", busy.join(", "));
            return Err(AppError::with_status(words, 409));
        }
        if let Some(new) = &chosen {
            Self::can_write_in(new, named)?;
        }
        let old = self.models.cache_dir();
        if let (Carry::Move, Some(new)) = (carry, chosen.clone()) {
            let (models, target) = (Arc::clone(&self.models), new.clone());
            let switch = Box::new(move || models.folders.work.set(&target));
            let files = FileMove { from: old, to: new, names: self.own_names() };
            return self.models.start_move(files, switch);
        }
        let result = Self::with_made(&self.models.clear(), self.models.clear_scratches(&live));
        // The scout's own folders go when nothing else lies in them; the folder the operator named stays, with whatever else he keeps there.
        drop(fs::remove_dir(self.models.scratch_root()));
        drop(fs::remove_file(self.models.downloaded.file()));
        match &chosen {
            Some(folder) => self.models.folders.work.set(folder),
            None => self.models.folders.work.forget(),
        }
        self.forget_figures();
        let new = self.models.cache_dir();
        // absent-ok: a clearing says the two together.
        let freed = result.get("freedBytes").and_then(Value::as_i64).unwrap_or(0);
        Log::line(&format!(
            "[llama-node] {named} moved from {} to {}: removed {} file(s) this scout kept there, freed {} bytes",
            old.display(),
            new.display(),
            Coerce::text(result.get("removed")),
            Thousands::of(freed)
        ));
        Ok(
            json!({"dir": new.display().to_string(), "chosen": chosen.is_some(), "removed": result.get("removed"), "freedBytes": freed}),
        )
    }

    /// The folder `text` names, if this shelf may lie there: an absolute path out of the model cache's folder, whose count would take its files for files the scout did not download.
    fn work_folder_of(&self, text: &str) -> Result<PathBuf, AppError> {
        let path = ModelFetcher::expanded(text);
        if !path.is_absolute() {
            return Err(AppError::new(format!("{} must be an absolute path: {text}", self.models.shelf.named)));
        }
        let path = Resolved::of(&path);
        let cache = Resolved::of(&self.models.model_cache_dir());
        if path.starts_with(&cache) {
            return Err(AppError::new(format!(
                "{} may not lie in the cache's folder {}: choose a folder of its own",
                self.models.shelf.named,
                cache.display()
            )));
        }
        Ok(path)
    }

    /// Refuses a cache folder that would hold the folder chosen for Strata's files, for the same reason.
    pub(super) fn refuse_over_work(&self, cache: &Path) -> Result<(), AppError> {
        match self.models.folders.work.value().map(|work| Resolved::of(&work)) {
            Some(work) if work.starts_with(cache) => Err(AppError::new(format!(
                "the cache may not hold the folder for Strata's files {}: choose another folder for one of them",
                work.display()
            ))),
            _ => Ok(()),
        }
    }

    /// What the board reads of this shelf (`work` in the cache's report): where it lies and whether the operator chose it; what it keeps — the copies of the models and what the cells made from them
    /// — and the budget over the copies, the operator's or the shelf's own; the disk it lies on, and whether that disk spins, as the system says it. Nothing is measured while no folder is chosen:
    /// the shelf is empty then, and a start that needs it is refused.
    pub fn work_facts(&self) -> Value {
        let chosen = self.models.folder_chosen();
        let mut out = Map::new();
        out.insert("dir".to_string(), json!(self.models.cache_dir().display().to_string()));
        out.insert("chosen".to_string(), json!(chosen));
        out.insert("budgetBytes".to_string(), json!(self.budget.value()));
        out.insert("budgetChosen".to_string(), json!(self.budget.chosen().is_some()));
        if chosen {
            out.extend(self.measured(|| self.measure_work()));
        }
        Value::Object(out)
    }

    fn measure_work(&self) -> Map<String, Value> {
        let dir = self.models.cache_dir();
        let (models, made) = (self.models.footprint(), self.models.scratch_bytes());
        let mut copies: Vec<(String, u64)> = self
            .models
            .downloaded
            .paths()
            .iter()
            .filter(|path| path.exists())
            .filter_map(|path| Some((path.strip_prefix(&dir).ok()?.display().to_string(), ModelFetcher::size_of(path))))
            .collect();
        copies.sort_by_key(|(_, bytes)| std::cmp::Reverse(*bytes));
        copies.truncate(8);
        let rows: Vec<Value> = copies.iter().map(|(name, bytes)| json!({"name": name, "bytes": bytes})).collect();
        let mut out = Map::new();
        out.insert("bytes".to_string(), json!(models + made));
        out.insert("modelsBytes".to_string(), json!(models));
        out.insert("madeBytes".to_string(), json!(made));
        out.insert("models".to_string(), Value::Array(rows));
        out.insert("disk".to_string(), Self::disk(&dir));
        let probe = dir.ancestors().find(|folder| folder.exists()).unwrap_or(&dir);
        if let Some(spins) = Disk::rotational(probe) {
            out.insert("rotational".to_string(), json!(spins));
        }
        out
    }
}
