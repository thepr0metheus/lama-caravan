//! Updating a model file in place, and flagging that a cell is still running the old one.

use super::downloads::{DownloadFile, Downloads};
use super::watch::ModelWatch;
use crate::app::App;
use os::Disk;
use rules::{AppError, Coerce, PyRepr};
use serde_json::{Map, Value, json};
use std::path::{Path, PathBuf};

#[cfg(test)]
mod tests;

/// The view.
pub struct ModelStaging<'app> {
    app: &'app App,
}

impl<'app> ModelStaging<'app> {
    const DISK_MARGIN_BYTES: i64 = 2 * 1024 * 1024 * 1024;
    const GIB: i64 = 1 << 30;

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn free_bytes(path: &Path) -> i64 {
        // absent-ok: a disk that says nothing has no room to promise: the check below refuses.
        path.parent().and_then(Disk::usage).map_or(0, |(_, free)| free as i64)
    }

    /// Whether there's enough room.
    pub fn check_room(live: &Path, need_bytes: i64) -> Result<Value, AppError> {
        let need = need_bytes + Self::DISK_MARGIN_BYTES;
        let free = Self::free_bytes(live);
        if free < need {
            return Err(AppError::with_status(
                format!(
                    "not enough room: need {} GB (new build + {} GB margin), free {} GB",
                    need / Self::GIB,
                    Self::DISK_MARGIN_BYTES / Self::GIB,
                    free / Self::GIB
                ),
                409,
            ));
        }
        Ok(json!({"free": free, "need": need}))
    }

    fn prev_path(live: &str) -> PathBuf {
        PathBuf::from(format!("{live}.prev"))
    }

    /// Preserves the current file as a hard link before it gets replaced: losing the only copy of the old build is not an option, so what cannot be
    /// kept is an error, and the update does not start. `""`: there is no file to keep.
    fn link_prev(live: &Path) -> std::io::Result<String> {
        if !live.is_file() {
            return Ok(String::new());
        }
        let prev = Self::prev_path(&live.to_string_lossy());
        // A `.prev` that will not go stops here. It may be this very file under its other name, an update that never landed: a copy over it would empty both.
        if prev.symlink_metadata().is_ok() {
            std::fs::remove_file(&prev)?;
        }
        if std::fs::hard_link(live, &prev).is_err() {
            // A file system with no links takes a copy. One that fails halfway goes: a Revert would put it over the working file.
            if let Err(error) = Self::copy_with_its_time(live, &prev) {
                drop(std::fs::remove_file(&prev));
                return Err(error);
            }
        }
        Ok(prev.to_string_lossy().into_owned())
    }

    /// A copy that keeps the file's time: a Revert brings back what the freshness check saw.
    fn copy_with_its_time(from: &Path, to: &Path) -> std::io::Result<()> {
        std::fs::copy(from, to)?;
        std::fs::File::options().write(true).open(to)?.set_modified(std::fs::metadata(from)?.modified()?)
    }

    /// Restores the previous build.
    pub fn restore_prev(live: &str) -> Result<Value, AppError> {
        let prev = Self::prev_path(live);
        if !prev.is_file() {
            return Err(AppError::with_status("no previous build kept for this file", 404));
        }
        std::fs::rename(&prev, live).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        Ok(json!({"ok": true, "restored": live}))
    }

    /// Deletes the kept previous build: frees up its size.
    pub fn drop_prev(live: &str) -> Result<Value, AppError> {
        let prev = Self::prev_path(live);
        let Ok(meta) = std::fs::metadata(&prev) else {
            return Ok(json!({"ok": true, "freed": 0}));
        };
        std::fs::remove_file(&prev).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        Ok(json!({"ok": true, "freed": meta.len()}))
    }

    /// Where a kept previous build lives.
    pub fn prev_overview(&self) -> Value {
        let report = ModelWatch::of(self.app).report();
        let mut out = Map::new();
        for repo in report.get("repos").and_then(Value::as_object).into_iter().flat_map(|repos| repos.values()) {
            for (key, row) in repo.get("files").and_then(Value::as_object).into_iter().flatten() {
                let live = Coerce::text(row.get("localPath"));
                if live.is_empty() {
                    continue;
                }
                let prev = Self::prev_path(&live);
                if let Ok(meta) = std::fs::metadata(&prev) {
                    out.insert(key.clone(), json!({"prev": prev.to_string_lossy(), "prevSize": meta.len()}));
                }
            }
        }
        Value::Object(out)
    }

    fn row_for(&self, key: &str) -> Option<(Value, String)> {
        let report = ModelWatch::of(self.app).report();
        report.get("repos").and_then(Value::as_object).into_iter().flatten().find_map(|(repo, row)| {
            row.get("files")?.get(key).filter(|found| Coerce::truthy(Some(*found))).map(|found| (found.clone(), repo.clone()))
        })
    }

    /// Downloads the new build ON TOP OF the working file.
    pub fn start_update(&self, key: &str) -> Result<Value, AppError> {
        let key = Coerce::strip(key);
        let Some((row, repo)) = self.row_for(key) else {
            return Err(AppError::with_status(format!("{key}: not in the last freshness report — run a check first"), 404));
        };
        let state = row.get("state").and_then(Value::as_str);
        if !matches!(state, Some("size" | "date")) {
            return Err(AppError::with_status(
                format!("{key}: nothing newer to fetch (state {})", PyRepr::of_value(row.get("state").unwrap_or(&Value::Null))),
                409,
            ));
        }
        let live = PathBuf::from(Coerce::text(row.get("localPath")));
        if !live.is_file() {
            return Err(AppError::with_status(format!("{key}: the local file is gone — re-run the check"), 404));
        }
        let remote_path = Coerce::text(row.get("remotePath"));
        if remote_path.is_empty() {
            return Err(AppError::with_status(format!("{key}: the report has no path on HF"), 409));
        }
        // absent-ok: `int(need_bytes or 0)`: a report with no size asks only for the margin.
        let size = Coerce::whole(row.get("remoteSize"));
        Self::check_room(&live, size)?;
        let keep_prev = ModelWatch::of(self.app).settings().get("keepPrev") == Some(&json!(true));
        let kept = if keep_prev {
            let failed = |error: std::io::Error| {
                AppError::with_status(format!("{key}: the old build could not be kept, nothing started: {error}"), 500)
            };
            Self::link_prev(&live).map_err(failed)?
        } else {
            String::new()
        };
        let models_dir = self.app.models_dir();
        let Some(dest_dir) = live.parent().and_then(|parent| parent.strip_prefix(&models_dir).ok()) else {
            return Err(AppError::with_status(format!("{key}: lives outside the models directory"), 409));
        };
        let name = live.file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
        let file = DownloadFile { path: remote_path, name, dest_dir: dest_dir.to_string_lossy().into_owned(), size };
        let job = Downloads::of(self.app).start(&repo, vec![file], &models_dir.to_string_lossy(), &self.app.hf_token());
        Ok(json!({"ok": true, "jobId": job, "file": key, "path": live.to_string_lossy(), "prev": kept}))
    }

    /// The working file's path: from the same report as everything else.
    pub fn live_path_for(&self, key: &str) -> Result<String, AppError> {
        let path = self.row_for(key).map(|(row, _)| Coerce::text(row.get("localPath"))).filter(|path| !path.is_empty());
        path.ok_or_else(|| AppError::with_status(format!("{key}: not in the last freshness report"), 404))
    }
}
