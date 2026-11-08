//! How much the machine's model cache keeps, which models, the trim that deletes the rest, and where the cache is.
//!
//! The owner, 2026-10-18, when a machine's disk was 94 % full of model copies and a start died with "No space left on device": keep only the last models. 2026-10-26: say it in GB, not in
//! models, and let the cache be in a folder of his choosing. The trim reaches the files in the record of downloads and no others; the rest are FOREIGN: counted and shown, deleted only when the
//! operator asks with the figure he was shown. "The last models" are those of the last starts that got as far as a running process; a model a cell uses now stays whatever its age. Nothing is
//! deleted while the log is empty: "unknown" is not "nothing".

use crate::errors::AppError;
use crate::log::{Log, Thousands};
use crate::models::cache_off::LibraryFinder;
use crate::models::fetcher::ModelFetcher;
use crate::models::files::{Resolved, SplitGguf, Walk};
use crate::models::uses::{CacheBudget, CacheKeep, ModelUses};
use crate::state::ScoutState;
use os::Disk;
use os::clock::Clock;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, PoisonError};

/// What the keeper asks of the cells, at the moment it deletes.
pub trait CellsInUse: Send + Sync {
    /// The model files the running cells hold.
    fn held_files(&self) -> Vec<String>;
    /// The cells that are starting or running, by their names.
    fn live_cells(&self) -> BTreeSet<String>;
    /// The cells whose start is still bringing its files.
    fn loading_cells(&self) -> BTreeSet<String>;
    /// How a refusal names these cells to the operator, one word each.
    fn called(&self, cells: &BTreeSet<String>) -> Vec<String>;
}

/// Figures measured: when, after how many moves of a folder, and what they are.
#[derive(Clone)]
struct Measured {
    at: f64,
    moves: u64,
    figures: Map<String, Value>,
}

/// The cache's keeper.
pub struct CacheKeeper {
    /// The setting of how many.
    pub keep: CacheKeep,
    /// The setting of how much.
    pub budget: CacheBudget,
    /// What was started.
    pub uses: ModelUses,
    pub(super) models: Arc<ModelFetcher>,
    pub(super) cells: Arc<dyn CellsInUse>,
    splits: Arc<SplitGguf>,
    clock: Arc<dyn Clock>,
    /// A trim or a deletion can take a while: one at a time, and the report of the cache never waits for it.
    pub(super) busy: Mutex<()>,
    memo: Mutex<Option<Measured>>,
}

impl CacheKeeper {
    /// How long the measured figures are reused: the heartbeat and the controller's polls both ask.
    const MEMO_SECONDS: f64 = 20.0;

    /// The keeper of this shelf: its settings and its log are its own.
    pub fn new(
        state: &Arc<ScoutState>,
        models: Arc<ModelFetcher>,
        cells: Arc<dyn CellsInUse>,
        splits: Arc<SplitGguf>,
        clock: Arc<dyn Clock>,
    ) -> Self {
        let shelf = models.shelf;
        Self {
            keep: CacheKeep::new(Arc::clone(state)),
            budget: CacheBudget::new(Arc::clone(state), shelf.budget_key, shelf.budget_default),
            uses: ModelUses::new(Arc::clone(state), Arc::clone(&clock), shelf.uses_key),
            models,
            cells,
            splits,
            clock,
            busy: Mutex::new(()),
            memo: Mutex::new(None),
        }
    }

    /// The start of `cell` ran: records it, and deletes what is beyond the setting now that the new model is in.
    pub fn commit(&self, cell: &str) -> Value {
        self.uses.commit(cell);
        self.trim()
    }

    /// Where these files are on this machine: in the cache, under the name the controller gave, every part of a split GGUF.
    pub fn files_of(&self, files: &[String]) -> BTreeSet<PathBuf> {
        let cache = self.models.cache_dir();
        let mut out = BTreeSet::new();
        for raw in files {
            for name in self.splits.parts(raw) {
                let path = ModelFetcher::expanded(&name);
                out.insert(Resolved::of(&if path.is_absolute() { path } else { cache.join(path) }));
            }
        }
        out
    }

    pub(super) fn files_of_entry(&self, entry: &Value) -> BTreeSet<PathBuf> {
        let names: Vec<String> =
            entry.get("files").and_then(Value::as_array).into_iter().flatten().map(|name| Coerce::text(Some(name))).collect();
        self.files_of(&names)
    }

    /// What these files take on the disk: a folder model by the files under it; a file that is not there takes nothing.
    fn size_of<'a>(paths: impl Iterator<Item = &'a PathBuf>) -> u64 {
        paths
            .map(|path| {
                if path.is_dir() {
                    Walk::files_with_sizes(path).iter().map(|(_, size)| *size).sum()
                } else {
                    // absent-ok: a file that is not there takes nothing.
                    path.symlink_metadata().map_or(0, |meta| meta.len())
                }
            })
            .sum()
    }

    /// The files of every cell that is starting or running and of every running process.
    pub(super) fn in_use(&self, uses: &[Value]) -> BTreeSet<PathBuf> {
        let live = self.cells.live_cells();
        let mut out: BTreeSet<PathBuf> =
            self.cells.held_files().iter().filter(|path| !path.is_empty()).map(|path| Resolved::of(Path::new(path))).collect();
        for entry in uses {
            if ModelUses::cell_of(entry).is_some_and(|cell| live.contains(cell)) {
                out.extend(self.files_of_entry(entry));
            }
        }
        out
    }

    /// What is not deleted: the files of every cell that is starting or running and of every running process, and then the models that ran, newest first: with a budget as many as fit in it together
    /// with those, a model that does not fit making room for an older one that does; without one the last `keep`.
    pub fn protected(&self) -> BTreeSet<PathBuf> {
        let uses = self.uses.entries();
        let mut out = self.in_use(&uses);
        let ran = uses.iter().filter(|entry| Coerce::truthy(entry.get("ok")));
        let Some(budget) = self.budget.value() else {
            for entry in ran.take(usize::try_from(self.keep.value()).unwrap_or(1)) {
                out.extend(self.files_of_entry(entry));
            }
            return out;
        };
        let mut total = Self::size_of(out.iter());
        for entry in ran {
            let files: BTreeSet<PathBuf> = self.files_of_entry(entry).difference(&out).cloned().collect();
            let size = Self::size_of(files.iter());
            if !files.is_empty() && total + size <= budget as u64 {
                out.extend(files);
                total += size;
            }
        }
        out
    }

    fn rule(&self) -> String {
        match self.budget.value() {
            Some(budget) => format!("keeps {} GiB of models", budget as f64 / (1u64 << 30) as f64),
            None => format!("keeps the last {} model(s)", self.keep.value()),
        }
    }

    /// Deletes the cached models beyond the setting: only what this scout downloaded. `waiting`: the log knows no model that ran, so nothing is known about what was used last and nothing is deleted.
    pub fn trim(&self) -> Value {
        let _one_at_a_time = self.busy.lock().unwrap_or_else(PoisonError::into_inner);
        // A move copies the files a trim would delete: the next start's end trims.
        if self.uses.newest(1).is_empty() || self.models.relocation.is_moving() {
            return json!({"removed": 0, "freedBytes": 0, "waiting": true});
        }
        let protected = self.protected();
        let keep: Vec<String> = protected.iter().map(|path| path.display().to_string()).collect();
        let result = self.models.purge(&keep);
        let made = self.models.clear_scratches(&self.scratch_kept(&protected));
        let result = Self::with_made(&result, made);
        self.forget_figures();
        let removed = result.get("removed").and_then(Value::as_u64);
        if let Some(count) = removed.filter(|count| *count != 0) {
            // absent-ok: the purge says the two together.
            let freed = result.get("freedBytes").and_then(Value::as_i64).unwrap_or(0);
            Log::line(&format!(
                "[llama-node] cache {}: removed {count} file(s), freed {} bytes",
                self.rule(),
                Thousands::of(freed)
            ));
        }
        json!({"removed": result.get("removed"), "freedBytes": result.get("freedBytes"), "waiting": false})
    }

    /// The operator's number: kept, and the cache trimmed to it at once.
    pub fn set_keep(&self, raw: &Value) -> Result<Value, AppError> {
        let keep = self.keep.set(raw)?;
        let trimmed = self.trim();
        Ok(
            json!({"keep": keep, "removed": trimmed.get("removed"), "freedBytes": trimmed.get("freedBytes"), "waiting": trimmed.get("waiting")}),
        )
    }

    /// The operator's size: kept, and the cache trimmed to it at once.
    pub fn set_budget(&self, raw: &Value) -> Result<Value, AppError> {
        let budget = self.budget.set(raw)?;
        let trimmed = self.trim();
        Ok(
            json!({"budgetBytes": budget, "removed": trimmed.get("removed"), "freedBytes": trimmed.get("freedBytes"), "waiting": trimmed.get("waiting")}),
        )
    }

    /// Whether `what` can be in `folder`: it is made, and written in.
    pub(super) fn can_write_in(folder: &Path, what: &str) -> Result<(), AppError> {
        let probe = folder.join(".caravan-write-probe");
        fs::create_dir_all(folder).and_then(|()| fs::write(&probe, b"")).and_then(|()| fs::remove_file(&probe)).map_err(|error| {
            AppError::new(format!("{what} cannot be in {}: {}", folder.display(), crate::errors::OsWords::of(&error)))
        })
    }

    /// A library nobody named yet, looked for on this machine: what the operator named stays, right or wrong, until the operator changes it.
    pub fn find_library(&self) {
        if self.models.off.library().is_some() {
            return;
        }
        if let Some(found) = LibraryFinder::here() {
            self.models.off.set(self.models.off.is_off(), Some(&found));
            self.forget_figures();
        }
    }

    /// The cache turned off or on (the owner, 2026-11-02). Off, a model comes through the controller; `library` names a folder of this machine to read it from instead, which must be there. What this scout
    /// downloaded goes, but for what a running cell holds. Not while a start is bringing its files: they would land in a cache that is going.
    pub fn set_off(&self, off: &Value, library: &Value) -> Result<Value, AppError> {
        let Some(off) = off.as_bool() else {
            return Err(AppError::new("off must be true or false"));
        };
        let refused = || AppError::new("library must be a folder on this machine: where it reads the models with the cache off");
        let named = Coerce::stripped(Some(library).filter(|said| Coerce::truthy(Some(*said))));
        let named = if named.is_empty() { None } else { Some(ModelFetcher::expanded(&named)) };
        if named.as_ref().is_some_and(|path| !path.is_absolute() || !path.is_dir()) {
            return Err(refused());
        }
        if !off {
            self.models.off.set(false, named.as_deref());
            self.forget_figures();
            let library = self.models.off.library().map(|path| path.display().to_string());
            return Ok(json!({"off": false, "library": library, "removed": 0, "freedBytes": 0}));
        }
        if named.is_none() && !self.models.view.possible() {
            return Err(AppError::with_status(
                "this machine cannot read a model through the controller: fusermount3 is not there (install fuse3), or name the folder where the library is mounted".to_string(),
                409,
            ));
        }
        let _one_at_a_time = self.busy.lock().unwrap_or_else(PoisonError::into_inner);
        self.models.relocation.refuse_while_moving()?;
        self.refuse_while_loading("the cache does not turn off")?;
        self.models.off.set(true, named.as_deref());
        self.models.off.choose(named.is_some());
        let cleared = self.clear_unheld();
        self.prune_empty();
        self.forget_figures();
        let library = named.map(|path| path.display().to_string());
        Ok(json!({"off": true, "library": library, "removed": cleared.get("removed"), "freedBytes": cleared.get("freedBytes")}))
    }

    /// Figures `measure` takes, reused for a few seconds: the heartbeat and the controller's polls both ask. A keeper measures one way only: the cache's figures, or the other shelf's.
    pub(super) fn measured(&self, measure: impl FnOnce() -> Map<String, Value>) -> Map<String, Value> {
        // A move that ended since the figures were measured changed them all.
        let (now, moves) = (self.clock.monotonic(), self.models.relocation.ended());
        let memo = self.memo.lock().unwrap_or_else(PoisonError::into_inner).clone();
        let hit = memo.filter(|said| said.moves == moves && now - said.at <= Self::MEMO_SECONDS);
        hit.map_or_else(
            || {
                let figures = measure();
                *self.memo.lock().unwrap_or_else(PoisonError::into_inner) =
                    Some(Measured { at: now, moves, figures: figures.clone() });
                figures
            },
            |said| said.figures,
        )
    }

    /// The model cache's setting and the figures the board shows. The figures are reused for a few seconds; the setting is read each time.
    pub fn facts(&self) -> Map<String, Value> {
        let figures = self.measured(|| self.measure());
        let mut out = Map::new();
        out.insert("keep".to_string(), json!(self.keep.value()));
        out.insert("budgetBytes".to_string(), json!(self.budget.value()));
        out.insert("dir".to_string(), json!(self.models.cache_dir().display().to_string()));
        // A folder the operator chose, and not where a cache lies by itself: only that one is worth giving back to a new scout.
        out.insert("dirChosen".to_string(), json!(self.models.folder_chosen()));
        // Where it goes back to when the chosen folder is removed: the board names it before it asks.
        out.insert("dirOwn".to_string(), json!(self.models.cache_dir_by_itself().display().to_string()));
        out.extend(self.models.off.facts());
        out.extend(self.models.relocation.facts());
        out.extend(figures);
        out
    }

    /// What was deleted changes the figures: the next report measures again.
    pub fn forget_figures(&self) {
        *self.memo.lock().unwrap_or_else(PoisonError::into_inner) = None;
    }

    fn measure(&self) -> Map<String, Value> {
        let cache = self.models.cache_dir();
        let foreign = self.foreign_files();
        let mut folders: BTreeMap<String, (u64, u64)> = BTreeMap::new();
        for (path, size) in &foreign {
            let top = path
                .strip_prefix(&cache)
                .ok()
                .and_then(|rel| rel.components().next())
                .map_or_else(String::new, |part| part.as_os_str().to_string_lossy().into_owned());
            let row = folders.entry(top).or_default();
            row.0 += 1;
            row.1 += size;
        }
        let mut biggest: Vec<(String, (u64, u64))> = folders.into_iter().collect();
        biggest.sort_by_key(|(_, (_, bytes))| std::cmp::Reverse(*bytes));
        biggest.truncate(8);
        let rows: Vec<Value> =
            biggest.iter().map(|(name, (files, bytes))| json!({"folder": name, "files": files, "bytes": bytes})).collect();
        let bytes: u64 = foreign.iter().map(|(_, size)| *size).sum();
        let mut out = Map::new();
        // What the cells made from the cache's models lies in it and takes its disk like a copy.
        out.insert("managedBytes".to_string(), json!(self.models.footprint() + self.models.scratch_bytes()));
        out.insert("foreign".to_string(), json!({"files": foreign.len(), "bytes": bytes, "folders": rows}));
        out.insert("disk".to_string(), Self::disk(&cache));
        out.insert("canThrough".to_string(), json!(self.models.view.possible()));
        out
    }

    /// The cache folder's disk: its size and what is free. The nearest folder that exists answers for one not made yet; `null` when the system will not say.
    pub(super) fn disk(cache: &Path) -> Value {
        let probe = cache.ancestors().find(|folder| folder.exists()).unwrap_or(cache);
        Disk::usage(probe).map_or(Value::Null, |(total, free)| json!({"totalBytes": total, "freeBytes": free}))
    }
}
