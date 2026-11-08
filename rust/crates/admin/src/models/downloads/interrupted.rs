//! The downloads a restart interrupted: listed, discarded or taken up again.

use super::*;

/// What an interrupted job still has to fetch, as the manifest beside its partial says: the file the partial is of, then the files of the job after it
/// (`rest`, written since 2026-11-03: before, a restart forgot them, and the resume of a five-file set brought one file) that are neither on the disk nor
/// written by a running job. A manifest of an older controller names none: its job is its one file.
pub(super) struct InterruptedJob {
    current: DownloadFile,
    rest: Vec<DownloadFile>,
}

impl InterruptedJob {
    /// The job of the partial's manifest `said`, under the models folder `root`, `live` being where running jobs write. A list of the other files that cannot
    /// be read is refused, not guessed: a guess leaves a file of the job out unsaid.
    pub(super) fn read(said: &Value, current: DownloadFile, root: &Path, live: &[String]) -> Result<Self, String> {
        let named = match said.get("rest") {
            None | Some(Value::Null) => Vec::new(),
            Some(Value::Array(entries)) => entries.iter().map(Self::entry).collect::<Result<Vec<_>, _>>()?,
            Some(other) => return Err(format!("the manifest's list of the job's other files is not a list: {other}")),
        };
        let rest = named
            .into_iter()
            .filter(|file| !live.contains(&file.dest_path()) && !root.join(file.dest_path()).is_file())
            .collect();
        Ok(Self { current, rest })
    }

    fn entry(raw: &Value) -> Result<DownloadFile, String> {
        let file = DownloadFile::of(raw);
        if file.path.is_empty() || !file.lands_inside() {
            return Err(format!("the manifest names a file of the job it cannot fetch into the models folder: {raw}"));
        }
        Ok(file)
    }

    /// Every file a resume fetches, the partial's first.
    pub(super) fn files(&self) -> Vec<DownloadFile> {
        std::iter::once(&self.current).chain(&self.rest).cloned().collect()
    }
}

impl<'app> Downloads<'app> {
    pub(super) fn live_paths(&self) -> Vec<String> {
        let jobs = self.jobs();
        jobs.values()
            .filter(|job| !Coerce::truthy(job.get("done")))
            .flat_map(|job| job.get("filePaths").and_then(Value::as_array).into_iter().flatten())
            .filter_map(|path| path.as_str().map(str::to_string))
            .collect()
    }

    /// Partials on disk that no running job owns, as job-shaped rows.
    pub fn scan_interrupted(&self, models_dir: &str) -> Vec<Value> {
        let now = self.app.now();
        {
            let scan = self.app.downloads.scan.lock().unwrap_or_else(PoisonError::into_inner);
            if let Some((at, folder, rows)) = scan.as_ref()
                && folder == models_dir
                && now - at < Self::SCAN_TTL
            {
                return rows.clone();
            }
        }
        let root = Path::new(models_dir);
        let live = self.live_paths();
        let mut rows = Vec::new();
        for partial in Walker::ending_in(root, ".part") {
            let Some(row) = Self::interrupted_row(&partial, root, &live) else {
                continue;
            };
            rows.push(row);
        }
        *self.app.downloads.scan.lock().unwrap_or_else(PoisonError::into_inner) =
            Some((now, models_dir.to_string(), rows.clone()));
        rows
    }

    /// The row of one partial: the job it stands for, its files the partial's and those after it still to fetch. A manifest whose other files cannot be read
    /// is a source this controller cannot tell, like a manifest it cannot read: the row is not resumable.
    pub(super) fn interrupted_row(partial: &Path, root: &Path, live: &[String]) -> Option<Value> {
        let full = partial.file_name()?.to_string_lossy().into_owned();
        let name = full.strip_suffix(".part")?.to_string();
        let dest_dir = partial.parent()?.strip_prefix(root).ok()?.to_string_lossy().into_owned();
        let owner = if dest_dir.is_empty() { name.clone() } else { format!("{dest_dir}/{name}") };
        if live.contains(&owner) {
            return None;
        }
        let meta = std::fs::metadata(partial).ok()?;
        let done = meta.size() as i64;
        let manifest = Self::read_manifest(partial);
        let label = if dest_dir.is_empty() { ".".to_string() } else { dest_dir.clone() };
        let repo = Coerce::text(manifest.get("repo"));
        // absent-ok: a manifest that says no size promises none.
        let size = Coerce::whole(manifest.get("size"));
        let shown_path = if label == "." { format!("./{name}") } else { format!("{label}/{name}") };
        let started = manifest
            .get("started_at")
            .filter(|said| Coerce::truthy(Some(*said)))
            .cloned()
            .unwrap_or_else(|| json!(meta.mtime() as f64));
        let current = DownloadFile { path: Coerce::text(manifest.get("path")), name: name.clone(), dest_dir, size };
        let job = InterruptedJob::read(&manifest, current.clone(), root, live);
        let files = job.as_ref().map_or_else(|_| vec![current.clone()], InterruptedJob::files);
        let names: Vec<&str> = files.iter().map(|file| file.name.as_str()).collect();
        let paths: Vec<String> = std::iter::once(shown_path.clone()).chain(files.iter().skip(1).map(Self::shown)).collect();
        // A size one file does not say leaves the whole unknown: a sum without it would be drawn as the whole.
        let total: i64 = if files.iter().all(|file| file.size > 0) { files.iter().map(|file| file.size).sum() } else { 0 };
        let resumable = !repo.is_empty() && !current.path.is_empty() && job.is_ok();
        Some(
            json!({"jobId": format!("part:{label}/{name}"), "status": "interrupted", "done": false, "error": null, "repo": repo, "title": if repo.is_empty() { label.clone() } else { repo.clone() }, "created_at": started, "finished_at": null, "total_files": files.len(), "fileNames": names, "filePaths": paths, "total_bytes": total, "total_bytes_done": done, "current_idx": 0, "current_file": name, "current_path": shown_path, "file_bytes_done": done, "file_bytes_total": size, "resumable": resumable, "destDir": label}),
        )
    }

    /// Where a file of a job lands, as a row shows it: `./name` at the top of the models folder.
    fn shown(file: &DownloadFile) -> String {
        let path = file.dest_path();
        if path.contains('/') { path } else { format!("./{path}") }
    }

    /// Deletes one orphaned partial; what it freed.
    pub fn discard_interrupted(&self, models_dir: &str, dest_dir: &str, name: &str) -> Result<i64, String> {
        if !DownloadFile::is_plain_name(name) || !DownloadFile::folder_stays_inside(dest_dir) {
            return Err("invalid destDir or name".to_string());
        }
        let owner =
            DownloadFile { path: String::new(), name: name.to_string(), dest_dir: dest_dir.to_string(), size: 0 }.dest_path();
        if self.live_paths().contains(&owner) {
            return Err("a running download is writing this file: stop it first".to_string());
        }
        let root = Path::new(models_dir);
        let partial = root.join(dest_dir).join(format!("{name}.part"));
        let freed = std::fs::metadata(&partial).map_err(|_| "this partial is gone".to_string())?.size() as i64;
        std::fs::remove_file(&partial).map_err(|_| "this partial is gone".to_string())?;
        Self::drop_manifest(&partial);
        if let Some(parent) = partial.parent() {
            Folders::prune_empty(parent, root);
        }
        *self.app.downloads.scan.lock().unwrap_or_else(PoisonError::into_inner) = None;
        Ok(freed)
    }

    /// Re-issues an interrupted job: the partial's file and the files of its job after it that are still to fetch.
    pub fn resume_interrupted(&self, models_dir: &str, token: &str, dest_dir: &str, name: &str) -> Result<String, AppError> {
        if !DownloadFile::folder_stays_inside(dest_dir) {
            return Err(AppError::new("invalid destDir"));
        }
        if !DownloadFile::is_plain_name(name) {
            return Err(AppError::new("invalid name"));
        }
        let partial = Path::new(models_dir).join(dest_dir).join(format!("{name}.part"));
        let Some(manifest) =
            std::fs::read(Self::manifest_path(&partial)).ok().and_then(|raw| serde_json::from_slice::<Value>(&raw).ok())
        else {
            return Err(AppError::new("no manifest for this partial — cannot tell which repo it came from"));
        };
        let (repo, path) = (Coerce::text(manifest.get("repo")), Coerce::text(manifest.get("path")));
        if repo.is_empty() || path.is_empty() {
            return Err(AppError::new("manifest is missing the repo or file path"));
        }
        // absent-ok: a manifest that says no size promises none.
        let size = Coerce::whole(manifest.get("size"));
        let current = DownloadFile { path, name: name.to_string(), dest_dir: dest_dir.to_string(), size };
        let job = InterruptedJob::read(&manifest, current, Path::new(models_dir), &self.live_paths()).map_err(AppError::new)?;
        Ok(self.start(&repo, job.files(), models_dir, token))
    }
}
