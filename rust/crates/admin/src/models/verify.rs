//! Comparing the local copy to Hugging Face by content, not by guesswork.

use super::hub::HubHash;
use crate::app::App;
use crate::common::artifacts::ModelArtifacts;
use net::{Sha1Stream, Sha256};
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};
use std::collections::HashMap;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::sync::{Mutex, MutexGuard, PoisonError};

mod copy;
#[cfg(test)]
mod tests;
pub use copy::CheckpointCopy;
pub use copy::CheckpointFile;
pub use copy::CheckpointLayout;

/// What a verify job knows of one copy, as its rows come in.
#[derive(Debug, Clone)]
struct CheckpointResult {
    folder: String,
    planned: usize,
    rows: Map<String, Value>,
}

impl CheckpointResult {
    fn snapshot(&self) -> Value {
        let mut summary = Map::new();
        summary.insert("files".to_string(), json!(self.planned));
        summary.insert("pending".to_string(), json!(self.planned - self.rows.len()));
        for state in CheckpointFile::STATES {
            let count = self.rows.values().filter(|row| row.get("state").and_then(Value::as_str) == Some(state)).count();
            summary.insert(state.to_string(), json!(count));
        }
        json!({"folder": self.folder, "files": self.rows, "summary": summary})
    }
}

/// One file to read.
enum Work {
    /// A GGUF of the repository.
    Gguf { name: String, path: String, hash: HubHash },
    /// A file of a checkpoint whose size is right and whose hash the hub gave.
    Checkpoint { result: usize, file: CheckpointFile, path: String },
}

impl Work {
    fn label(&self) -> &str {
        match self {
            Self::Gguf { name, .. } => name,
            Self::Checkpoint { file, .. } => &file.repo_path,
        }
    }

    fn path(&self) -> &str {
        match self {
            Self::Gguf { path, .. } | Self::Checkpoint { path, .. } => path,
        }
    }

    fn is_git(&self) -> bool {
        matches!(self, Self::Checkpoint { file, .. } if matches!(file.hub_hash, HubHash::GitSha1(_)))
    }
}

/// A job.
struct VerifyJob {
    doc: Map<String, Value>,
    results: Vec<CheckpointResult>,
}

/// The jobs and the digests worked out so far.
#[derive(Default)]
pub struct VerifyMemory {
    jobs: Mutex<Vec<(String, VerifyJob)>>,
    digests: Mutex<HashMap<(bool, String, i64, i128), String>>,
}

/// The view.
pub struct ModelVerify<'app> {
    app: &'app App,
}

impl<'app> ModelVerify<'app> {
    const CHUNK: usize = 4 * 1024 * 1024;
    const KEEP_JOBS: usize = 8;

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn jobs(&self) -> MutexGuard<'_, Vec<(String, VerifyJob)>> {
        self.app.verify_memory.jobs.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn with_job(&self, id: &str, work: impl FnOnce(&mut VerifyJob)) {
        if let Some((_, job)) = self.jobs().iter_mut().find(|(said, _)| said == id) {
            work(job);
        }
    }

    /// A file's digest of the kind the hub gave for it, kept by (kind, path, size, mtime): sixty gigabytes are read once. `on_progress` hears each chunk, or the whole size at once for a digest already known.
    pub fn file_digest(&self, path: &str, git: bool, mut on_progress: impl FnMut(i64)) -> std::io::Result<String> {
        let meta = std::fs::metadata(path)?;
        let size = meta.size() as i64;
        let key = (git, path.to_string(), size, i128::from(meta.mtime()) * 1_000_000_000 + i128::from(meta.mtime_nsec()));
        let known = self.app.verify_memory.digests.lock().unwrap_or_else(PoisonError::into_inner).get(&key).cloned();
        if let Some(known) = known {
            on_progress(size);
            return Ok(known);
        }
        let mut file = std::fs::File::open(path)?;
        let mut chunk = vec![0u8; Self::CHUNK];
        let value = if git {
            let mut digest = Sha1Stream::new();
            digest.update(format!("blob {size}\0").as_bytes());
            Self::feed(&mut file, &mut chunk, &mut on_progress, |bytes| digest.update(bytes))?;
            digest.hex()
        } else {
            let mut digest = Sha256::new();
            Self::feed(&mut file, &mut chunk, &mut on_progress, |bytes| digest.update(bytes))?;
            digest.hex()
        };
        self.app.verify_memory.digests.lock().unwrap_or_else(PoisonError::into_inner).insert(key, value.clone());
        Ok(value)
    }

    fn feed(
        file: &mut std::fs::File,
        chunk: &mut [u8],
        on_progress: &mut impl FnMut(i64),
        mut take: impl FnMut(&[u8]),
    ) -> std::io::Result<()> {
        loop {
            let read = file.read(chunk)?;
            let Some(bytes) = chunk.get(..read).filter(|bytes| !bytes.is_empty()) else {
                return Ok(());
            };
            take(bytes);
            on_progress(read as i64);
        }
    }

    /// What is left to read, its size, and what a checkpoint's copy already settled without a byte.
    fn work_of(files: &[Value], local_files: &Value, copies: Vec<CheckpointCopy>) -> (Vec<Work>, i64, Vec<CheckpointResult>) {
        let (mut works, mut total, mut results) = (Vec::new(), 0, Vec::new());
        for file in files {
            let name = Coerce::text(file.get("name"));
            let local = local_files.get(&name);
            let path = Coerce::text(local.and_then(|local| local.get("path")));
            if !name.is_empty() && !path.is_empty() {
                // absent-ok: `int(local.get("size") or 0)`: what is not sized adds nothing to the bar.
                total += Coerce::int_or_zero(local.and_then(|local| local.get("size"))).unwrap_or(0);
                works.push(Work::Gguf { name, path, hash: HubHash::from_entry(file) });
            }
        }
        for copy in copies {
            let mut result = CheckpointResult { folder: copy.folder, planned: copy.files.len(), rows: Map::new() };
            for file in copy.files {
                if let Some(row) = file.settled() {
                    result.rows.insert(file.repo_path.clone(), row);
                } else {
                    let local = file.local.as_ref();
                    // absent-ok: a file past `settled` has its size: this figure is only the bar's.
                    total += local.and_then(|local| local.get("size")).and_then(Value::as_i64).unwrap_or(0);
                    let path = Coerce::text(local.and_then(|local| local.get("path")));
                    works.push(Work::Checkpoint { result: results.len(), file, path });
                }
            }
            results.push(result);
        }
        (works, total, results)
    }

    /// Starts verifying a repository; a running job of it is that job. `files` and `local_files` are the GGUFs; `copies` the checkpoint's folders.
    pub fn start(
        &self,
        repo: &str,
        files: &[Value],
        local_files: &Value,
        copies: Vec<CheckpointCopy>,
    ) -> Result<String, AppError> {
        let repo = Coerce::strip(repo);
        if repo.is_empty() {
            return Err(AppError::new("missing repo"));
        }
        let (works, total, results) = Self::work_of(files, local_files, copies);
        if works.is_empty() && results.is_empty() {
            return Err(AppError::new("nothing of this repo is on disk"));
        }
        let mut jobs = self.jobs();
        if let Some((id, _)) = jobs
            .iter()
            .find(|(_, job)| !Coerce::truthy(job.doc.get("done")) && job.doc.get("repo").and_then(Value::as_str) == Some(repo))
        {
            return Ok(id.clone());
        }
        let id = format!("{}-{}", self.app.now_whole(), jobs.len());
        let doc = json!({"id": id, "repo": repo, "done": false, "error": null, "files": {}, "checkpoints": [], "totalFiles": works.len(), "totalBytes": total, "bytesDone": 0, "currentFile": "", "currentIdx": 0, "startedAt": self.app.now(), "finishedAt": null});
        jobs.push((id.clone(), VerifyJob { doc: Coerce::fields(&doc), results }));
        drop(jobs);
        let Some(app) = self.app.shared() else {
            return Ok(id);
        };
        let job_id = id.clone();
        let started =
            std::thread::Builder::new().name("hf-verify".to_string()).spawn(move || ModelVerify::of(&app).run(&job_id, works));
        if let Err(error) = started {
            self.with_job(&id, |job| {
                job.doc.insert("error".to_string(), json!(error.to_string()));
                job.doc.insert("done".to_string(), json!(true));
            });
        }
        Ok(id)
    }

    fn run(&self, job_id: &str, works: Vec<Work>) {
        for (index, work) in works.iter().enumerate() {
            self.with_job(job_id, |job| {
                job.doc.insert("currentFile".to_string(), json!(work.label()));
                job.doc.insert("currentIdx".to_string(), json!(index));
            });
            let digest = self.file_digest(work.path(), work.is_git(), |count| {
                self.with_job(job_id, |job| {
                    // absent-ok: the figure is set when a job is made.
                    let done = Coerce::i64_or_zero(job.doc.get("bytesDone"));
                    job.doc.insert("bytesDone".to_string(), json!(done + count));
                });
            });
            self.with_job(job_id, |job| Self::store(job, work, digest.as_deref().map_err(ToString::to_string)));
        }
        let now = self.app.now();
        self.with_job(job_id, |job| {
            job.doc.insert("done".to_string(), json!(true));
            job.doc.insert("finishedAt".to_string(), json!(now));
        });
        self.trim();
    }

    fn store(job: &mut VerifyJob, work: &Work, digest: Result<&str, String>) {
        match work {
            Work::Gguf { name, hash, .. } => {
                let row = match digest {
                    Ok(actual) => {
                        let expected = if let HubHash::Sha256(value) = hash { value.as_str() } else { "" };
                        let state = if expected.is_empty() {
                            "unknown"
                        } else if actual == expected {
                            "same"
                        } else {
                            "differs"
                        };
                        json!({"state": state, "sha256": actual, "expected": expected, "hash": hash.kind()})
                    }
                    Err(error) => json!({"state": "unreadable", "error": error, "hash": hash.kind()}),
                };
                if let Some(files) = job.doc.get_mut("files").and_then(Value::as_object_mut) {
                    files.insert(name.clone(), row);
                }
            }
            Work::Checkpoint { result, file, .. } => {
                let row = match digest {
                    Ok(actual) => file.judged(actual),
                    Err(error) => file.unreadable(&error),
                };
                if let Some(result) = job.results.get_mut(*result) {
                    result.rows.insert(file.repo_path.clone(), row);
                }
            }
        }
    }

    fn trim(&self) {
        let mut jobs = self.jobs();
        // absent-ok: a done job's moment is set when it ends; one with none goes first.
        let when = |job: &VerifyJob| job.doc.get("finishedAt").and_then(Value::as_f64).unwrap_or(0.0);
        let mut done: Vec<(f64, String)> =
            jobs.iter().filter(|(_, job)| Coerce::truthy(job.doc.get("done"))).map(|(id, job)| (when(job), id.clone())).collect();
        done.sort_by(|left, right| left.0.total_cmp(&right.0));
        let doomed = done.len().saturating_sub(Self::KEEP_JOBS);
        let doomed: Vec<String> = done.into_iter().take(doomed).map(|(_, id)| id).collect();
        jobs.retain(|(id, _)| !doomed.contains(id));
    }

    /// A job's status: by id, or by repository, for the page.
    pub fn status(&self, job_id: &str, repo: &str) -> Value {
        let jobs = self.jobs();
        // absent-ok: a job's moment is set when it is made.
        let started = |job: &VerifyJob| job.doc.get("startedAt").and_then(Value::as_f64).unwrap_or(0.0);
        let job = if job_id.is_empty() {
            jobs.iter()
                .filter(|(_, job)| job.doc.get("repo").and_then(Value::as_str) == Some(repo))
                .max_by(|left, right| started(&left.1).total_cmp(&started(&right.1)))
        } else {
            jobs.iter().find(|(id, _)| id == job_id)
        };
        let Some((_, job)) = job else {
            return json!({"ok": true, "job": null});
        };
        let mut doc = job.doc.clone();
        doc.insert("checkpoints".to_string(), Value::Array(job.results.iter().map(CheckpointResult::snapshot).collect()));
        json!({"ok": true, "job": doc})
    }
}
