//! The downloads a restart interrupted: listed, discarded or taken up again.

use super::*;

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
        Some(
            json!({"jobId": format!("part:{label}/{name}"), "status": "interrupted", "done": false, "error": null, "repo": repo, "title": if repo.is_empty() { label.clone() } else { repo.clone() }, "created_at": started, "finished_at": null, "total_files": 1, "fileNames": [name], "filePaths": [shown_path], "total_bytes": size, "total_bytes_done": done, "current_idx": 0, "current_file": name, "current_path": shown_path, "file_bytes_done": done, "file_bytes_total": size, "resumable": !repo.is_empty() && Coerce::truthy(manifest.get("path")), "destDir": label}),
        )
    }

    /// Deletes one orphaned partial; what it freed.
    pub fn discard_interrupted(&self, models_dir: &str, dest_dir: &str, name: &str) -> Result<i64, String> {
        if !DownloadFile::is_plain_name(name) || dest_dir.starts_with('/') || dest_dir.split('/').any(|part| part == "..") {
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

    /// Re-issues the job for one orphaned partial.
    pub fn resume_interrupted(&self, models_dir: &str, token: &str, dest_dir: &str, name: &str) -> Result<String, AppError> {
        if dest_dir.contains("..") || dest_dir.starts_with('/') {
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
        Ok(self.start(
            &repo,
            vec![DownloadFile { path, name: name.to_string(), dest_dir: dest_dir.to_string(), size }],
            models_dir,
            token,
        ))
    }
}
