//! What a shelf gives back: the room a copy needs, and what the cells made from models it no longer keeps. The other half of `CacheKeeper`.

use crate::models::fetcher::ModelFetcher;
use crate::models::files::Resolved;
use crate::models::keeper::CacheKeeper;
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::path::PathBuf;
use std::sync::PoisonError;

impl CacheKeeper {
    /// A clearing's answer with what the cells made added to it: (the files, the bytes).
    pub(super) fn with_made(cleared: &Value, made: (u64, u64)) -> Value {
        // absent-ok: a clearing says the two together.
        let count = |key: &str| cleared.get(key).and_then(Value::as_u64).unwrap_or(0);
        json!({"removed": count("removed") + made.0, "freedBytes": count("freedBytes") + made.1})
    }

    /// The cells whose scratch stays: those starting or running, and those whose model the cache keeps. What a cell made from its model goes the way its model goes: it is made again in seconds, and three
    /// Strata cells' packs lay on a disk for weeks, 6.6 GB nobody was told of, after their models had gone (2026-11-02).
    pub(super) fn scratch_kept(&self, protected: &BTreeSet<PathBuf>) -> BTreeSet<i64> {
        let mut ports = self.cells.live_ports();
        for entry in self.uses.entries() {
            let files = self.files_of_entry(&entry);
            let port = entry.get("port").and_then(Value::as_i64);
            ports.extend(port.filter(|_| !files.is_empty() && files.is_subset(protected)));
        }
        ports
    }

    /// The operator's Clear, and the cache going off: every copy and everything made from one goes, but for what a cell that is starting or running uses.
    pub fn clear_unheld(&self) -> Value {
        let cleared = self.models.purge(&self.cells.held_files());
        let result = Self::with_made(&cleared, self.models.clear_scratches(&self.cells.live_ports()));
        self.forget_figures();
        result
    }

    /// Room for a copy of `bytes`, called `label`, while a start brings its model: the copies no cell uses go, those not used for longest first, and only until it fits — on the disk, and on a
    /// shelf of a size within its budget. The words of why it does not fit, otherwise. Older copies are otherwise trimmed after a start that ran, and that start cannot run on a full disk.
    pub fn make_room(&self, bytes: u64, label: &str) -> Result<(), String> {
        let free = || self.models.disk_free();
        self.room_until(bytes, ModelFetcher::LEFT_FREE, &free).map_err(|short| self.short_words(short, bytes, label))
    }

    /// Why a copy of `bytes` does not fit now, with `left` bytes the disk must keep beside it; `None` when it fits. A disk that does not say is not refused: nothing is known against it.
    fn short_of(&self, bytes: u64, left: u64, free: &dyn Fn() -> Option<u64>) -> Option<Short> {
        if let Some(free) = free().filter(|free| *free < bytes.saturating_add(left)) {
            return Some(Short::Disk { free });
        }
        let budget = self.budget.value().filter(|_| self.models.shelf.budget_bounds_copies)?;
        // absent-ok: a budget is a whole number of bytes from 1 GiB up (uses.rs); a negative one is no number this reads.
        let budget = u64::try_from(budget).unwrap_or(0);
        let held = self.models.footprint();
        (held.saturating_add(bytes) > budget).then_some(Short::Budget { budget, held })
    }

    pub(super) fn room_until(&self, bytes: u64, left: u64, free: &dyn Fn() -> Option<u64>) -> Result<(), Short> {
        let _one_at_a_time = self.busy.lock().unwrap_or_else(PoisonError::into_inner);
        if self.short_of(bytes, left, free).is_none() {
            return Ok(());
        }
        let uses = self.uses.entries();
        let keep: Vec<String> = self.in_use(&uses).iter().map(|path| path.display().to_string()).collect();
        let live = self.cells.live_ports();
        let named: BTreeSet<PathBuf> = uses.iter().flat_map(|entry| self.files_of_entry(entry)).collect();
        // A copy no start names is older than any the log remembers.
        let unnamed: Vec<String> = self
            .models
            .downloaded
            .paths()
            .into_iter()
            .filter(|path| !named.contains(&Resolved::of(path)))
            .map(|path| path.display().to_string())
            .collect();
        if !unnamed.is_empty() {
            self.models.evict(&unnamed, &keep);
        }
        for entry in uses.iter().rev() {
            if self.short_of(bytes, left, free).is_none() {
                break;
            }
            let files: Vec<String> = self.files_of_entry(entry).iter().map(|path| path.display().to_string()).collect();
            self.models.evict(&files, &keep);
            if let Some(port) = entry.get("port").and_then(Value::as_i64).filter(|port| !live.contains(port)) {
                self.models.clear_scratch(port);
            }
        }
        self.forget_figures();
        self.short_of(bytes, left, free).map_or(Ok(()), Err)
    }

    /// The words of a copy that does not fit: what it takes, what stands in its way, and what the operator can do.
    fn short_words(&self, short: Short, bytes: u64, label: &str) -> String {
        let shelf = self.models.shelf;
        let gb = |bytes: u64| format!("{:.1} GB", bytes as f64 / f64::from(1u32 << 30));
        match short {
            Short::Disk { free } => self.models.no_room_words(label, bytes, free),
            Short::Budget { budget, .. } if bytes > budget => format!(
                "no room for {label}: it takes {}, more than the {} {} may keep. Nothing was copied. {}",
                gb(bytes),
                gb(budget),
                shelf.named,
                shelf.when_over
            ),
            Short::Budget { budget, held } => format!(
                "no room for {label}: it takes {}, and {} may keep {}, {} of which are models a running cell uses. Nothing was copied. {}",
                gb(bytes),
                shelf.named,
                gb(budget),
                gb(held),
                shelf.when_over
            ),
        }
    }
}

/// Why a copy does not fit, with every copy no cell uses gone.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Short {
    /// The disk: what it has free.
    Disk {
        /// Bytes free.
        free: u64,
    },
    /// The shelf's budget, and what the copies that stay take of it.
    Budget {
        /// The budget, bytes.
        budget: u64,
        /// What the copies that stay take, bytes.
        held: u64,
    },
}
