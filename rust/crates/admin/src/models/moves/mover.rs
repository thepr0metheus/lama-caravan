//! Runs one job to its end: copy, prove the copy by reading it back past this host's cache, let it settle on the library's disk, and only then take the source away.

use super::job::{MoveFile, MoveJob, SETTLE_S};
use crate::app::App;
use crate::models::gc::ModelGc;
use crate::models::headers::ModelHeader;
use crate::models::store_probe::{MARKER_NAME, StoreProbe};
use net::Sha256;
use rules::Coerce;
use serde_json::Value;
use std::io::{self, Read, Seek, SeekFrom, Write};
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::time::Duration;

mod scan;

mod copy;

mod finish;

#[cfg(test)]
mod tests;

/// Why a move stops short of its file.
enum Stop {
    /// The operator stopped the job.
    Cancelled,
    /// An operation failed.
    Failed(io::Error),
}

impl From<io::Error> for Stop {
    fn from(error: io::Error) -> Self {
        Self::Failed(error)
    }
}

/// A job as the worker and the pages share it.
pub type SharedJob = Arc<Mutex<MoveJob>>;

/// The mover.
pub struct Mover<'app> {
    app: &'app App,
    job: SharedJob,
    save: &'app (dyn Fn(&MoveJob) + Sync),
}

impl<'app> Mover<'app> {
    const PART_SUFFIX: &'static str = ".caravan-part";
    const CHUNK: usize = if cfg!(test) { 1000 } else { 4 * 1024 * 1024 };
    const CHECKPOINT_BYTES: i64 = if cfg!(test) { 3000 } else { 256 * 1024 * 1024 };
    const WAIT_S: u64 = if cfg!(test) { 3 } else { 30 };
    /// One beat of a wait.
    const BEAT: Duration = if cfg!(test) { Duration::from_millis(1) } else { Duration::from_secs(1) };
    const MAX_ATTEMPTS: i64 = 2;
    const MAX_ERRORS: i64 = 5;

    /// The mover of a job; `save` writes its manifest.
    pub fn new(app: &'app App, job: SharedJob, save: &'app (dyn Fn(&MoveJob) + Sync)) -> Self {
        Self { app, job, save }
    }

    fn locked(&self) -> MutexGuard<'_, MoveJob> {
        self.job.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// A change of the job, written down.
    fn edit<R>(&self, change: impl FnOnce(&mut MoveJob) -> R) -> R {
        let mut job = self.locked();
        let out = change(&mut job);
        (self.save)(&job);
        out
    }

    /// A change of the job's figures only: the page reads them, the manifest takes them at the next checkpoint.
    fn quiet<R>(&self, change: impl FnOnce(&mut MoveJob) -> R) -> R {
        change(&mut self.locked())
    }

    fn check_cancel(&self) -> Result<(), Stop> {
        if self.locked().cancel { Err(Stop::Cancelled) } else { Ok(()) }
    }

    fn roots(&self) -> (PathBuf, PathBuf) {
        let job = self.locked();
        (PathBuf::from(job.source_root()), PathBuf::from(job.target_root()))
    }

    fn file_of(&self, item: usize, file: usize) -> Option<MoveFile> {
        self.locked().items.get(item)?.files.get(file).cloned()
    }

    fn on_file(&self, job: &mut MoveJob, item: usize, file: usize, change: impl FnOnce(&mut MoveFile)) {
        if let Some(found) = job.items.get_mut(item).and_then(|row| row.files.get_mut(file)) {
            change(found);
        }
    }

    /// The whole job.
    pub fn run(&self) {
        let cancelled = self.locked().cancel;
        let mut result = if cancelled { Err(Stop::Cancelled) } else { Ok(()) };
        if result.is_ok() {
            self.edit(|job| {
                job.status = "running".to_string();
                job.reason.clear();
            });
            let count = self.locked().items.len();
            for item in 0..count {
                if self.locked().items.get(item).is_some_and(|row| !row.is_final()) {
                    result = self.item(item);
                    if result.is_err() {
                        break;
                    }
                }
            }
        }
        if matches!(result, Err(Stop::Cancelled)) {
            let count = self.locked().items.len();
            for item in 0..count {
                if self.locked().items.get(item).is_some_and(|row| !row.is_final()) {
                    self.close(item, "cancelled", "", "");
                }
            }
        }
        // A job that broke says why, and nobody pressed Stop: its items stay as they stood, with the source of each still in place.
        let (status, reason) = match &result {
            Ok(()) => ("done", String::new()),
            Err(Stop::Cancelled) => ("cancelled", String::new()),
            Err(Stop::Failed(error)) => ("failed", error.to_string()),
        };
        let now = self.app.now_whole();
        self.edit(|job| {
            job.status = status.to_string();
            job.reason = reason;
            job.finished_at = now;
        });
    }

    fn item(&self, item: usize) -> Result<(), Stop> {
        let (folder, scanned) =
            self.locked().items.get(item).map_or((String::new(), true), |row| (row.folder.clone(), row.scanned));
        if !folder.is_empty() && !scanned && !self.scan(item, &folder)? {
            return Ok(());
        }
        // absent-ok: an item the job does not hold has no files.
        let count = self.locked().items.get(item).map_or(0, |row| row.files.len());
        for file in 0..count {
            let proven = self.file_of(item, file).is_some_and(|found| found.state == "proven");
            if !proven && !self.bring(item, file)? {
                return Ok(());
            }
        }
        if !folder.is_empty() && !self.retrying(item, |mover| mover.plant(item))? {
            return Ok(());
        }
        let to_library = self.locked().target.get("kind").and_then(Value::as_str) == Some("library");
        if to_library {
            self.settle(item)?;
        }
        let mut why = String::new();
        if !self.retrying(item, |mover| {
            mover.stores_here()?;
            why = mover.why_keep(item)?;
            Ok(())
        })? {
            return Ok(());
        }
        if !why.is_empty() {
            self.close(item, "skipped", &why, "");
            return Ok(());
        }
        self.edit(|job| {
            if let Some(row) = job.items.get_mut(item) {
                row.state = "removing".to_string();
            }
        });
        if self.remove(item, &folder) {
            self.forget_headers(item);
            self.close(item, "done", "", "");
        }
        Ok(())
    }

    /// Runs an operation until it goes, or its failures close the item: `false` then.
    fn retrying(&self, item: usize, mut work: impl FnMut(&Self) -> io::Result<()>) -> Result<bool, Stop> {
        loop {
            match work(self) {
                Ok(()) => return Ok(true),
                Err(error) => {
                    if !self.trouble(item, &error)? {
                        return Ok(false);
                    }
                }
            }
        }
    }

    fn remove(&self, item: usize, folder: &str) -> bool {
        let (source_root, _) = self.roots();
        if !folder.is_empty() {
            let place = source_root.join(folder);
            // A link where a folder was planned: removing it would say the folder is gone, and the folder stays where the link points.
            if place.is_symlink() {
                self.close(item, "skipped", "unlink-failed", &format!("{} is a link", place.display()));
                return false;
            }
            match std::fs::remove_dir_all(&place) {
                Ok(()) => {}
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                Err(error) => {
                    self.close(item, "skipped", "unlink-failed", &error.to_string());
                    return false;
                }
            }
            self.quiet(|job| {
                for file in job.items.get_mut(item).into_iter().flat_map(|row| row.files.iter_mut()) {
                    file.phase = "removed".to_string();
                }
            });
            if let Some(parent) = place.parent() {
                self.prune_dirs(parent, &source_root);
            }
            return true;
        }
        // absent-ok: an item the job does not hold has no files.
        let count = self.locked().items.get(item).map_or(0, |row| row.files.len());
        for file in 0..count {
            let Some(found) = self.file_of(item, file) else {
                continue;
            };
            let source = source_root.join(&found.rel);
            match std::fs::remove_file(&source) {
                Ok(()) => {}
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                Err(error) => {
                    self.close(item, "skipped", "unlink-failed", &error.to_string());
                    return false;
                }
            }
            self.quiet(|job| self.on_file(job, item, file, |found| found.phase = "removed".to_string()));
            if let Some(parent) = source.parent() {
                self.prune_dirs(parent, &source_root);
            }
        }
        true
    }
}
