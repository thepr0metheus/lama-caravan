//! Background downloads from the hub with per-job progress. A partial stays beside its destination with a manifest, so a restart can name it and resume it;
//! the manifest names the files of the job after it too, so the resume is the job's and not its one file.

use super::hub::HubAccess;
use super::walk::Walker;
use crate::app::App;
use crate::common::misc::Folders;
use net::Randomness;
use plumbing::HttpError;
use rules::{AppError, Coerce, PythonJson};
use serde_json::{Map, Value, json};
use std::io::{Read, Write};
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard, PoisonError};
use std::time::Duration;

mod file;
mod interrupted;

#[cfg(test)]
mod tests;

pub use file::DownloadFile;

/// The jobs and the last scan for orphans.
#[derive(Default)]
pub struct DownloadMemory {
    jobs: Mutex<Map<String, Value>>,
    scan: Mutex<Option<(f64, String, Vec<Value>)>>,
}

/// How a job's fetch ended.
enum Stop {
    /// The operator pressed Cancel.
    Cancelled,
    /// It failed.
    Failed(HttpError),
}

/// The view.
pub struct Downloads<'app> {
    app: &'app App,
}

impl<'app> Downloads<'app> {
    const MAX_ATTEMPTS: u64 = 4;
    const RETRY_BACKOFF: [u64; 3] = if cfg!(test) { [0, 0, 0] } else { [3, 10, 30] };
    const SCAN_TTL: f64 = 5.0;

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn jobs(&self) -> MutexGuard<'_, Map<String, Value>> {
        self.app.downloads.jobs.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn update(&self, job_id: &str, fields: Value) {
        let mut jobs = self.jobs();
        if let (Some(Value::Object(job)), Value::Object(fields)) = (jobs.get_mut(job_id), fields) {
            job.extend(fields);
        }
    }

    fn figure(&self, job_id: &str, key: &str) -> i64 {
        // absent-ok: a job's figures are all set when it is made; a job gone has done nothing more.
        Coerce::i64_or_zero(self.jobs().get(job_id).and_then(|job| job.get(key)))
    }

    fn cancelled(&self, job_id: &str) -> bool {
        self.jobs().get(job_id).is_some_and(|job| Coerce::truthy(job.get("cancel")))
    }

    /// Forgets the jobs that ended more than `kept` seconds ago.
    pub fn forget_finished(&self, now: f64, kept: f64) {
        self.jobs()
            .retain(|_, job| job.get("finished_at").and_then(Value::as_f64).is_none_or(|at| at == 0.0 || now - at <= kept));
    }

    /// Every job, as the page lists them.
    pub fn all(&self) -> Map<String, Value> {
        self.jobs().clone()
    }

    /// One job.
    pub fn job(&self, job_id: &str) -> Option<Value> {
        self.jobs().get(job_id).cloned()
    }

    fn manifest_path(partial: &Path) -> PathBuf {
        // absent-ok: the partial file always has a name: it was made here.
        let mut name = partial.file_name().unwrap_or_default().to_os_string();
        name.push(".json");
        partial.with_file_name(name)
    }

    /// The manifest of the file in progress, with `rest`, the files of its job after it: the job is held in memory, and a restart leaves only what is on the
    /// disk. A restart in the instant between two files (the one renamed, the next one's manifest not written yet) still loses them: that instant, not a file's
    /// minutes.
    fn write_manifest(&self, partial: &Path, repo: &str, file: &DownloadFile, rest: &[DownloadFile]) {
        let rest: Vec<Value> = rest.iter().map(DownloadFile::said).collect();
        let doc = json!({"repo": repo, "path": file.path, "name": file.name, "destDir": file.dest_dir, "size": file.size, "started_at": self.app.now(), "rest": rest});
        // A partial with no manifest still resumes where it stands; only a restart cannot name it.
        drop(std::fs::write(Self::manifest_path(partial), PythonJson::spaced(&doc)));
    }

    fn read_manifest(partial: &Path) -> Value {
        std::fs::read(Self::manifest_path(partial))
            .ok()
            .and_then(|raw| serde_json::from_slice(&raw).ok())
            .unwrap_or_else(|| json!({}))
    }

    fn drop_manifest(partial: &Path) {
        // There may be none.
        drop(std::fs::remove_file(Self::manifest_path(partial)));
    }

    /// Discards a partial left over from another file or another build.
    fn drop_stale_partial(partial: &Path, repo: &str, file: &DownloadFile) {
        if !partial.exists() {
            return;
        }
        let saved = Self::read_manifest(partial);
        // absent-ok: a manifest with no size is no promise of this build.
        let size = Coerce::whole(saved.get("size"));
        let same = saved.get("repo").and_then(Value::as_str) == Some(repo)
            && saved.get("path").and_then(Value::as_str) == Some(&file.path)
            && size == file.size
            && size > 0;
        if !same {
            // What will not go is written over below.
            drop(std::fs::remove_file(partial));
            Self::drop_manifest(partial);
        }
    }

    /// The destinations of `files` that already hold a file.
    pub fn replaces_on_disk(files: &[DownloadFile], models_dir: &str) -> Vec<String> {
        let mut out: Vec<String> =
            files.iter().map(DownloadFile::dest_path).filter(|rel| Path::new(models_dir).join(rel).is_file()).collect();
        out.sort();
        out
    }

    /// Starts a job; a running job for the same files is that job.
    pub fn start(&self, repo: &str, files: Vec<DownloadFile>, models_dir: &str, token: &str) -> String {
        let mut names: Vec<String> = files.iter().map(|file| file.name.clone()).collect();
        names.sort();
        let mut paths: Vec<String> = files.iter().map(DownloadFile::dest_path).collect();
        paths.sort();
        {
            let jobs = self.jobs();
            let same = jobs.iter().find(|(_, job)| {
                !Coerce::truthy(job.get("done"))
                    && job.get("repo").and_then(Value::as_str) == Some(repo)
                    && job.get("filePaths") == Some(&json!(paths))
            });
            if let Some((id, _)) = same {
                return id.clone();
            }
        }
        // absent-ok: a system with no random bytes still names a job by its moment; nothing rests on the word being secret.
        let id = Randomness::bytes(8).map_or_else(
            || format!("{:x}", self.app.now_whole()),
            |bytes| bytes.iter().map(|byte| format!("{byte:02x}")).collect(),
        );
        let total: i64 = files.iter().map(|file| file.size).sum();
        self.jobs().insert(id.clone(), json!({"status": "running", "done": false, "error": null, "repo": repo, "title": repo, "created_at": self.app.now(), "finished_at": null, "total_files": files.len(), "fileNames": names, "filePaths": paths, "total_bytes": total, "total_bytes_done": 0, "current_idx": 0, "current_file": "", "current_path": "", "file_bytes_done": 0, "file_bytes_total": 0}));
        let Some(app) = self.app.shared() else {
            return id;
        };
        let (job, repo, models_dir, token) = (id.clone(), repo.to_string(), models_dir.to_string(), token.to_string());
        let started = std::thread::Builder::new()
            .name("hf-download".to_string())
            .spawn(move || Downloads::of(&app).run(&job, &repo, &files, &models_dir, &token));
        if let Err(error) = started {
            self.update(&id, json!({"done": true, "status": "error", "error": error.to_string(), "finished_at": self.app.now()}));
        }
        id
    }

    fn run(&self, job_id: &str, repo: &str, files: &[DownloadFile], models_dir: &str, token: &str) {
        let mut partial = None;
        let mut result = Ok(());
        let mut left = files;
        while let Some((file, rest)) = left.split_first() {
            let index = files.len() - left.len();
            left = rest;
            if self.cancelled(job_id) {
                result = Err(Stop::Cancelled);
                break;
            }
            self.update(job_id, json!({"current_idx": index, "current_file": file.name, "current_path": file.dest_path(), "file_bytes_done": 0, "file_bytes_total": file.size}));
            let dest_dir = Path::new(models_dir).join(&file.dest_dir);
            if let Err(error) = std::fs::create_dir_all(&dest_dir) {
                result = Err(Stop::Failed(HttpError::Io(error)));
                break;
            }
            let dest = dest_dir.join(&file.name);
            let temporary = dest_dir.join(format!("{}.part", file.name));
            partial = Some(temporary.clone());
            Self::adopt_legacy(&dest_dir, &file.name, &temporary);
            Self::drop_stale_partial(&temporary, repo, file);
            self.write_manifest(&temporary, repo, file, rest);
            if let Err(stop) = self.fetch(job_id, repo, file, &temporary, &dest, token) {
                result = Err(stop);
                break;
            }
        }
        self.finish(job_id, repo, token, partial.as_deref(), result);
    }

    /// A partial of the older naming, `<name>.part-*`: the newest goes on, the rest go.
    fn adopt_legacy(folder: &Path, name: &str, partial: &Path) {
        if partial.exists() {
            return;
        }
        let start = format!("{name}.part-");
        let mut legacy: Vec<PathBuf> = std::fs::read_dir(folder)
            .into_iter()
            .flatten()
            .flatten()
            .filter(|entry| entry.file_name().to_string_lossy().starts_with(&start))
            .map(|entry| entry.path())
            .collect();
        legacy.sort();
        if let Some(newest) = legacy.pop() {
            // A partial that will not move is fetched anew.
            drop(std::fs::rename(newest, partial));
        }
        for stray in legacy {
            // As above.
            drop(std::fs::remove_file(stray));
        }
    }

    fn fetch(&self, job_id: &str, repo: &str, file: &DownloadFile, partial: &Path, dest: &Path, token: &str) -> Result<(), Stop> {
        let url = format!("{}/{repo}/resolve/main/{}", self.app.hub(), file.path);
        let done_before = self.figure(job_id, "total_bytes_done");
        let mut attempt = 0;
        loop {
            attempt += 1;
            // absent-ok: no partial yet starts at the beginning.
            let mut offset = std::fs::metadata(partial).map_or(0, |meta| meta.size() as i64);
            self.update(job_id, json!({"attempt": attempt}));
            let tried = self.one_attempt(job_id, &url, file, partial, &mut offset, done_before, token);
            match tried {
                Ok(()) => {
                    std::fs::rename(partial, dest).map_err(|error| Stop::Failed(HttpError::Io(error)))?;
                    Self::drop_manifest(partial);
                    return Ok(());
                }
                Err(Stop::Cancelled) => return Err(Stop::Cancelled),
                Err(Stop::Failed(error)) => {
                    // absent-ok: as above.
                    let grew = std::fs::metadata(partial).map_or(0, |meta| meta.size() as i64) > offset;
                    if attempt >= Self::MAX_ATTEMPTS || HubAccess::is_wall(&error) || (!grew && attempt >= 2) {
                        return Err(Stop::Failed(error));
                    }
                    self.update(job_id, json!({"status": "retrying", "error": error.to_string()}));
                    let wait = Self::RETRY_BACKOFF.get(attempt as usize - 1).copied().unwrap_or(30);
                    std::thread::sleep(Duration::from_secs(wait));
                    self.update(job_id, json!({"status": "running", "error": null}));
                }
            }
        }
    }

    /// The answer's body into the file, as it comes; `(bytes in the file now)`.
    fn keep_body(
        &self,
        job_id: &str,
        answer: plumbing::HttpAnswer,
        mut output: std::fs::File,
        start: i64,
        done_before: i64,
    ) -> Result<i64, Stop> {
        let mut body = answer.body;
        let mut chunk = vec![0u8; 1 << 20];
        let mut downloaded = start;
        loop {
            if self.cancelled(job_id) {
                return Err(Stop::Cancelled);
            }
            let read = body.read(&mut chunk).map_err(|error| Stop::Failed(HttpError::Io(error)))?;
            let Some(bytes) = chunk.get(..read).filter(|bytes| !bytes.is_empty()) else {
                return Ok(downloaded);
            };
            output.write_all(bytes).map_err(|error| Stop::Failed(HttpError::Io(error)))?;
            downloaded += read as i64;
            self.update(job_id, json!({"file_bytes_done": downloaded, "total_bytes_done": done_before + downloaded}));
        }
    }

    #[allow(clippy::too_many_arguments, reason = "one attempt of a fetch: all of these are that attempt's own")]
    fn one_attempt(
        &self,
        job_id: &str,
        url: &str,
        file: &DownloadFile,
        partial: &Path,
        offset: &mut i64,
        done_before: i64,
        token: &str,
    ) -> Result<(), Stop> {
        let mut fields = HubAccess::fields(token);
        if *offset > 0 {
            fields.push(("Range", format!("bytes={offset}-")));
        }
        let answer = self.app.http.following_with(url, &fields, Duration::from_secs(120)).map_err(Stop::Failed)?;
        // absent-ok: an answer that does not say its length is read to its end.
        let length: i64 = answer.head.headers.text_of("Content-Length").trim().parse().unwrap_or(0);
        let resumed = *offset > 0 && answer.head.status == 206;
        let total = if resumed {
            *offset + length
        } else if length != 0 {
            length
        } else {
            file.size
        };
        // The hub may ignore a Range: the file starts again, and whether this attempt moved anything is counted from zero.
        *offset = if resumed { *offset } else { 0 };
        let start = *offset;
        self.update(
            job_id,
            json!({"file_bytes_total": total, "file_bytes_done": start, "total_bytes_done": done_before + start}),
        );
        let output = std::fs::OpenOptions::new()
            .create(true)
            .write(true)
            .append(resumed)
            .truncate(!resumed)
            .open(partial)
            .map_err(|error| Stop::Failed(HttpError::Io(error)))?;
        let downloaded = self.keep_body(job_id, answer, output, start, done_before)?;
        if total > 0 && downloaded != total {
            let words = format!(
                "incomplete download for {}: got {downloaded} of {total} bytes ({}%)",
                file.name,
                downloaded * 100 / total
            );
            return Err(Stop::Failed(HttpError::Io(std::io::Error::other(words))));
        }
        Ok(())
    }

    fn finish(&self, job_id: &str, repo: &str, token: &str, partial: Option<&Path>, result: Result<(), Stop>) {
        let now = self.app.now();
        match result {
            Ok(()) => self.update(job_id, json!({"done": true, "status": "done", "finished_at": now})),
            Err(Stop::Cancelled) => {
                if let Some(partial) = partial.filter(|partial| std::fs::metadata(partial).map_or(true, |meta| meta.size() == 0))
                {
                    // A partial with bytes in it stays, for a resume; an empty one goes.
                    drop(std::fs::remove_file(partial));
                    Self::drop_manifest(partial);
                }
                self.update(job_id, json!({"done": true, "status": "cancelled", "error": null, "finished_at": now}));
                *self.app.downloads.scan.lock().unwrap_or_else(PoisonError::into_inner) = None;
            }
            Err(Stop::Failed(error)) => {
                let mut fields = json!({"done": true, "status": "error", "error": error.to_string(), "finished_at": now});
                if let (Some(access), Value::Object(row)) =
                    (HubAccess::after(&self.app.http, self.app.hub(), &error, repo, token), &mut fields)
                {
                    row.insert("access".to_string(), access);
                }
                self.update(job_id, fields);
            }
        }
    }

    /// Asks a running job to stop; the job as it stands, none when it is gone or done.
    pub fn cancel(&self, job_id: &str) -> Option<Value> {
        let mut jobs = self.jobs();
        let job = jobs.get_mut(job_id).filter(|job| !Coerce::truthy(job.get("done")))?;
        job["cancel"] = json!(true);
        Some(job.clone())
    }
}
