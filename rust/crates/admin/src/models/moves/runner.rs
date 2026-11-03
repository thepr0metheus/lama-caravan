//! The move jobs of this process: one at a time, in the order they were asked for, each with its manifest in a folder of its own.

use super::job::{FINAL_ITEM_STATES, MoveJob};
use super::mover::{Mover, SharedJob};
use super::planner::{MovePlanner, MoveRefused};
use crate::app::App;
use crate::models::stores::StoreRefused;
use files::AtomicFile;
use plumbing::Log;
use rules::{Coerce, PythonJson};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

#[cfg(test)]
mod tests;

/// The jobs.
#[derive(Default)]
pub struct MoveMemory {
    jobs: Mutex<BTreeMap<String, SharedJob>>,
    worker: Mutex<bool>,
    current: Mutex<String>,
}

/// The view.
pub struct MoveRunner<'app> {
    app: &'app App,
}

impl<'app> MoveRunner<'app> {
    const KEEP_FINISHED: usize = 20;

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn jobs(&self) -> MutexGuard<'_, BTreeMap<String, SharedJob>> {
        self.app.moves.jobs.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn folder(&self) -> PathBuf {
        self.app.paths.store_moves_dir.clone()
    }

    fn written(&self, job: &MoveJob) -> Result<(), String> {
        let path = self.folder().join(format!("{}.json", job.id));
        AtomicFile::write(&path, PythonJson::spaced(&job.to_json()).as_bytes()).map_err(|error| error.to_string())
    }

    /// A job's figures on their way: one write that fails is one checkpoint lost, and a restart goes back to the one before.
    fn write(&self, job: &MoveJob) {
        if let Err(error) = self.written(job) {
            Log::line(&format!("store moves: {} not written: {error}", job.id));
        }
    }

    fn shared_jobs(&self) -> Vec<SharedJob> {
        self.jobs().values().map(Arc::clone).collect()
    }

    fn read(job: &SharedJob) -> MutexGuard<'_, MoveJob> {
        job.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// Starts a move: its plan or a refusal.
    pub fn start(
        &self,
        paths: &[Value],
        target_id: &str,
        source_id: Option<&str>,
        then: Option<&Value>,
    ) -> Result<Value, MoveRefused> {
        let busy: BTreeSet<String> =
            self.shared_jobs().iter().filter(|job| !Self::read(job).finished()).flat_map(|job| Self::read(job).paths()).collect();
        let mut job = MovePlanner::of(self.app).plan(paths, target_id, &busy, source_id)?;
        job.then = then.filter(|then| Coerce::truthy(Some(*then))).cloned().unwrap_or_else(|| json!({}));
        // Accepted means on disk, before the first byte: a job a restart forgets leaves its part in the library with nobody to finish it.
        self.written(&job)
            .map_err(|error| StoreRefused::refused(format!("the move could not be written down: {error}"), "not-written", 500))?;
        let summary = job.summary(self.app.now());
        self.jobs().insert(job.id.clone(), Arc::new(Mutex::new(job)));
        self.ensure_worker();
        Ok(summary)
    }

    /// Picks up what a restart interrupted; how many.
    pub fn resume(&self) -> usize {
        let mut names: Vec<PathBuf> = std::fs::read_dir(self.folder())
            .into_iter()
            .flatten()
            .flatten()
            .map(|entry| entry.path())
            .filter(|path| path.extension().is_some_and(|end| end == "json"))
            .collect();
        names.sort();
        let mut waiting = 0;
        for path in names {
            let parsed = std::fs::read(&path).ok().and_then(|raw| serde_json::from_slice::<Value>(&raw).ok());
            let Some(mut job) = parsed.and_then(|doc| MoveJob::of_json(&doc)) else {
                continue;
            };
            let mut jobs = self.jobs();
            if jobs.contains_key(&job.id) {
                continue;
            }
            if !job.finished() {
                job.status = "queued".to_string();
                job.reason.clear();
                waiting += 1;
            }
            jobs.insert(job.id.clone(), Arc::new(Mutex::new(job)));
        }
        self.prune();
        if waiting > 0 {
            self.ensure_worker();
        }
        waiting
    }

    /// Stops a move.
    pub fn cancel(&self, job_id: &str) -> Result<Value, MoveRefused> {
        let Some(shared) = self.jobs().get(job_id).map(Arc::clone) else {
            return Err(StoreRefused::refused(format!("no such move: {job_id}"), "unknown-job", 404));
        };
        let current = self.app.moves.current.lock().unwrap_or_else(PoisonError::into_inner).clone();
        let now = self.app.now();
        let mut job = Self::read(&shared);
        if !job.finished() {
            job.cancel = true;
            if job.status == "queued" && job.id != current {
                for item in job.items.iter_mut().filter(|item| !FINAL_ITEM_STATES.contains(&item.state.as_str())) {
                    item.state = "cancelled".to_string();
                }
                job.status = "cancelled".to_string();
                job.finished_at = now.trunc() as i64;
            }
            self.write(&job);
        }
        Ok(job.summary(now))
    }

    /// Every job, newest first.
    pub fn summaries(&self) -> Vec<Value> {
        let now = self.app.now();
        let mut jobs: Vec<MoveJob> = self.shared_jobs().iter().map(|job| Self::read(job).clone()).collect();
        jobs.sort_by(|left, right| right.created_at.cmp(&left.created_at).then_with(|| left.id.cmp(&right.id)));
        jobs.iter().map(|job| job.summary(now)).collect()
    }

    fn ensure_worker(&self) {
        let mut worker = self.app.moves.worker.lock().unwrap_or_else(PoisonError::into_inner);
        if *worker {
            return;
        }
        let Some(app) = self.app.shared() else {
            return;
        };
        *worker = true;
        let started = std::thread::Builder::new().name("store-moves".to_string()).spawn(move || MoveRunner::of(&app).work());
        if let Err(error) = started {
            *worker = false;
            Log::line(&format!("store moves: no thread: {error}"));
        }
    }

    fn work(&self) {
        loop {
            let next = {
                let mut worker = self.app.moves.worker.lock().unwrap_or_else(PoisonError::into_inner);
                let open: Vec<SharedJob> = self.shared_jobs().into_iter().filter(|job| !Self::read(job).finished()).collect();
                let picked = open.into_iter().min_by_key(|job| {
                    let job = Self::read(job);
                    (job.created_at, job.id.clone())
                });
                if picked.is_none() {
                    *worker = false;
                }
                picked
            };
            let Some(shared) = next else {
                return;
            };
            *self.app.moves.current.lock().unwrap_or_else(PoisonError::into_inner) = Self::read(&shared).id.clone();
            let save = |job: &MoveJob| self.write(job);
            let ran =
                std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| Mover::new(self.app, Arc::clone(&shared), &save).run()));
            if ran.is_err() {
                let now = self.app.now_whole();
                let mut job = Self::read(&shared);
                job.status = "failed".to_string();
                job.reason = "the move ended early".to_string();
                job.finished_at = now;
                self.write(&job);
            }
            self.app.moves.current.lock().unwrap_or_else(PoisonError::into_inner).clear();
            self.keep_promise(&shared);
            self.prune();
        }
    }

    /// What was waiting for this move: a cell to start, when all of it came home.
    fn keep_promise(&self, shared: &SharedJob) {
        let (then, done) = {
            let job = Self::read(shared);
            (
                job.then.get("start").filter(|start| Coerce::truthy(Some(*start))).cloned(),
                job.status == "done" && job.items.iter().all(|item| item.state == "done"),
            )
        };
        let (Some(start), true) = (then, done) else {
            return;
        };
        if let Err(error) = self.app.start_cell(&start) {
            let mut job = Self::read(shared);
            if job.reason.is_empty() {
                job.reason = format!("the cell did not start: {}", error.message);
            }
            self.write(&job);
        }
    }

    fn prune(&self) {
        let mut done: Vec<(i64, String)> = self
            .shared_jobs()
            .iter()
            .filter(|job| Self::read(job).finished())
            .map(|job| {
                // One hold of the job: two in one expression, and the second waits for the first for good.
                let job = Self::read(job);
                (job.created_at, job.id.clone())
            })
            .collect();
        done.sort_by(|left, right| right.0.cmp(&left.0).then_with(|| left.1.cmp(&right.1)));
        for (_, id) in done.into_iter().skip(Self::KEEP_FINISHED) {
            self.jobs().remove(&id);
            // One that will not go is read back as finished at the next start, and pruned then.
            drop(std::fs::remove_file(self.folder().join(format!("{id}.json"))));
        }
    }
}
