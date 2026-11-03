//! A model that is a folder: a checkpoint, a whisper cache, a robot policy, rebuilt in the cache through the controller. `ensure_folder` and its parts of `ModelFetcher`.

use crate::errors::AppError;
use crate::log::Log;
use crate::models::fetcher::{Fetch, ModelFetcher};
use crate::models::files::{OneSpaceJson, Resolved};
use rules::Coerce;
use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::PoisonError;
use std::time::Duration;
use wire::Percent;

impl ModelFetcher {
    /// Written last into a folder this scout rebuilt: its listing, so that a folder without it is one whose fetch did not finish.
    const FOLDER_MARK: &'static str = ".caravan-folder.json";

    /// Its listing, then each file through the download a file takes, then each link inside it. The files land in `<folder>.part`, and the folder takes its name only when everything is in place: a fetch
    /// cut short is resumed, and never read as a model. A folder this scout did not download is never replaced.
    pub fn ensure_folder(&self, raw: &str, fetch: &Fetch) -> Result<PathBuf, AppError> {
        let lock = self.copy_lock(raw);
        let _held = lock.lock().unwrap_or_else(PoisonError::into_inner);
        let local = self.cache_dir().join(raw);
        if fetch.use_cache && local.join(Self::FOLDER_MARK).is_file() && self.folder_is_current(raw, &local) {
            return Ok(local);
        }
        // Whose the folder there is, is asked before a byte is fetched. A folder of files this scout fetched one by one, another cell's start of the same model, is completed where it is.
        let whole = self.downloaded.has(&local);
        let is_link = local.symlink_metadata().is_ok_and(|meta| meta.file_type().is_symlink());
        let completed_here = !whole && local.is_dir() && !is_link && self.downloaded.foreign_in(&local).is_empty();
        if (local.exists() || is_link) && !(whole || completed_here) {
            return Err(Self::not_ours(&local));
        }
        let listing = self.folder_listing(raw)?;
        let part = if completed_here { local.clone() } else { local.with_file_name(format!("{}.part", Self::name_of(&local))) };
        fs::create_dir_all(&part).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        self.downloaded.add(&part);
        self.flying(&part, true);
        let filled = self.fill_folder(raw, &local, &part, &listing, fetch);
        self.flying(&part, false);
        filled
    }

    /// Whether the folder here is what the controller lists now: its listing was written into it when it was built. A controller that does not answer has nothing to say against a whole copy: a machine
    /// that starts its cells at boot may come up first.
    fn folder_is_current(&self, raw: &str, local: &Path) -> bool {
        let Ok(now) = self.folder_listing(raw) else {
            return true;
        };
        let built =
            fs::read_to_string(local.join(Self::FOLDER_MARK)).ok().and_then(|text| serde_json::from_str::<Value>(&text).ok());
        let same = built.is_some_and(|built| built.get("files") == now.get("files") && built.get("links") == now.get("links"));
        if !same {
            Log::line(&format!("[llama-node] {raw}: the folder here is not what the controller lists — bringing it again"));
        }
        same
    }

    fn name_of(path: &Path) -> String {
        path.file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned())
    }

    pub(super) fn not_ours(local: &Path) -> AppError {
        AppError::with_status(format!("{} is there and was not downloaded by this scout: not replaced", local.display()), 409)
    }

    fn fill_folder(&self, raw: &str, local: &Path, part: &Path, listing: &Value, fetch: &Fetch) -> Result<PathBuf, AppError> {
        let empty = Vec::new();
        let files = listing.get("files").and_then(Value::as_array).unwrap_or(&empty);
        let links = listing.get("links").and_then(Value::as_array).unwrap_or(&empty);
        let raw_name = Self::name_of(Path::new(raw));
        for (at, item) in files.iter().enumerate() {
            let rel = Coerce::text(item.get("path"));
            let target = Self::inside(part, &rel)?;
            let size = item.get("size").and_then(Value::as_u64);
            if target.metadata().is_ok_and(|meta| meta.is_file() && Some(meta.len()) == size) {
                continue;
            }
            Self::made_parent(&target)?;
            let label = format!("{raw_name}/{rel} ({}/{})", at + 1, files.len());
            let temporary = target.with_file_name(format!("{}.tmp", Self::name_of(&target)));
            self.download(&format!("{raw}/{rel}"), &target, &temporary, &label, fetch, false)?;
        }
        for item in links {
            Self::made_link(raw, part, item)?;
        }
        let mark = OneSpaceJson::text(listing).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        fs::write(part.join(Self::FOLDER_MARK), mark).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        if part != local {
            let is_link = local.symlink_metadata().is_ok_and(|meta| meta.file_type().is_symlink());
            if local.exists() || is_link {
                if !self.downloaded.has(local) {
                    return Err(Self::not_ours(local));
                }
                fs::remove_dir_all(local).map_err(|error| AppError::with_status(error.to_string(), 500))?;
            }
            fs::rename(part, local).map_err(|error| AppError::with_status(error.to_string(), 500))?;
            self.downloaded.add(local);
            self.downloaded.forget(part);
        }
        self.downloaded.forget_under(local);
        let bytes = Coerce::text(listing.get("size"));
        Log::line(&format!("[llama-node] folder complete: {raw} — {} files, {} links, {bytes} bytes", files.len(), links.len()));
        Ok(local.to_path_buf())
    }

    fn made_parent(path: &Path) -> Result<(), AppError> {
        match path.parent() {
            Some(parent) => fs::create_dir_all(parent).map_err(|error| AppError::with_status(error.to_string(), 500)),
            None => Ok(()),
        }
    }

    fn made_link(raw: &str, part: &Path, item: &Value) -> Result<(), AppError> {
        let rel = Coerce::text(item.get("path"));
        let at = Self::inside(part, &rel)?;
        let target = Coerce::text(item.get("target"));
        if Path::new(&target).is_absolute() {
            return Err(AppError::with_status(
                format!("the controller listed a link out of the folder {raw}: {rel} -> {target}"),
                502,
            ));
        }
        let beside = Path::new(&rel).parent().unwrap_or(Path::new("")).join(&target);
        Self::inside(part, &beside.to_string_lossy())?;
        Self::made_parent(&at)?;
        if at.symlink_metadata().is_ok() {
            fs::remove_file(&at).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        }
        std::os::unix::fs::symlink(&target, &at).map_err(|error| AppError::with_status(error.to_string(), 500))
    }

    /// The controller's listing of a model folder: `{files, links, size}`.
    pub(super) fn folder_listing(&self, raw: &str) -> Result<Value, AppError> {
        const TIMEOUT: Duration = Duration::from_secs(60);
        let url = format!("{}/api/models/folder?path={}", self.controller(raw)?, Percent::encode_path(raw));
        let listing = self.http.json("GET", &url, &self.token_fields(), &[], TIMEOUT).map_err(|error| {
            let words = match &error {
                crate::http_client::HttpError::Status(status, _) => format!("HTTP {status}"),
                other => other.to_string(),
            };
            AppError::with_status(format!("the controller does not list the model folder {raw}: {words}"), 502)
        })?;
        let is_listing = listing.get("files").is_some_and(Value::is_array) && listing.get("links").is_some_and(Value::is_array);
        if !is_listing {
            return Err(AppError::with_status(format!("the controller's listing of {raw} is not a folder listing"), 502));
        }
        Ok(listing)
    }

    /// `root/rel`, refused when `rel` leaves `root`: the listing comes over the network, and a path like `../../.ssh/authorized_keys` is written nowhere.
    pub fn inside(root: &Path, rel: &str) -> Result<PathBuf, AppError> {
        let refused =
            || AppError::with_status(format!("the controller listed a path that is not inside the folder: {rel:?}"), 502);
        if rel.is_empty() || Path::new(rel).is_absolute() {
            return Err(refused());
        }
        if !Resolved::of(&root.join(rel)).starts_with(Resolved::of(root)) {
            return Err(refused());
        }
        Ok(root.join(rel))
    }
}
