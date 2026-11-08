//! The model cache on this machine: where its files live, and how they arrive from the controller.

use crate::config::ScoutConfig;
use crate::errors::AppError;
use crate::http_client::HttpClient;
use crate::log::Log;
use crate::models::cache_off::CacheOff;
use crate::models::files::{DownloadedFiles, Resolved, SplitGguf};
use crate::models::folders::Folders;
use crate::models::relocate::Relocation;
use crate::models::shelf::{Shelf, ShelfParts};
use crate::models::space::FreeSpace;
use crate::models::view::LibraryView;
use os::clock::Clock;
use rules::Coerce;
use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::mpsc;
use std::sync::{Arc, Mutex, OnceLock, PoisonError};
use std::time::Duration;

/// Where the progress of a download goes: the startup state of the cell being started, by its name.
pub type Progress = Arc<dyn Fn(&str, Map<String, Value>) + Send + Sync>;

/// Makes room for a copy of this many bytes, called by this name; the third argument reads what the disk has free. Room now, or the words of why there is none.
pub type RoomMaker = Arc<dyn Fn(u64, &str, &dyn Fn() -> Option<u64>) -> Result<(), String> + Send + Sync>;

/// What one fetch is asked.
#[derive(Debug, Clone, Default)]
pub struct Fetch {
    /// Whether its progress is the cell's.
    pub report: bool,
    /// The short name shown during the copy; its file's name when empty.
    pub label: String,
    /// Whether a copy here is good enough.
    pub use_cache: bool,
    /// The cell it is for.
    pub cell: String,
    /// Where the controller reads it.
    pub hint: Option<Value>,
}

/// A shelf of copies: the model cache, or the folder for Strata's files (shelf.rs).
pub struct ModelFetcher {
    /// Which of the two, and where it differs from the other.
    pub shelf: &'static Shelf,
    pub(super) config: Arc<ScoutConfig>,
    pub(super) report: Progress,
    pub(super) folders: Arc<Folders>,
    /// Whether this machine keeps copies at all.
    pub off: Arc<CacheOff>,
    /// A model with no copy here, as a file a program can read: one view for both shelves, as it is one mount.
    pub view: Arc<LibraryView>,
    /// The moves of either shelf's folder: one at a time.
    pub relocation: Arc<Relocation>,
    pub(super) clock: Arc<dyn Clock>,
    pub(super) http: Arc<HttpClient>,
    /// The record of what is this scout's.
    pub downloaded: DownloadedFiles,
    pub(super) splits: Arc<SplitGguf>,
    /// What a disk has free: this shelf's, before a copy, and a new folder's, before a move.
    pub(super) disks: Arc<dyn FreeSpace>,
    /// Who makes room when a copy would not fit: the keeper, known only once it stands.
    pub(super) room_maker: OnceLock<RoomMaker>,
    /// One fetch per folder or file at a time: two cells of one model starting together would write the same `<folder>.part`.
    copying: Mutex<BTreeMap<String, Arc<Mutex<()>>>>,
    /// What is being written right now: a purge leaves these alone.
    in_flight: Mutex<BTreeSet<PathBuf>>,
}

impl ModelFetcher {
    pub(super) const SCRATCH: &'static str = ".cells";
    const PROBE: Duration = Duration::from_secs(3);
    const CORRUPT_PATTERNS: [&'static str; 3] =
        ["not within the file bounds", "corrupted or incomplete", "unexpected end of file"];

    /// The shelf `shelf` of these parts.
    pub fn new(parts: &ShelfParts, shelf: &'static Shelf) -> Self {
        let (settings, chosen) = (Arc::clone(&parts.config), Arc::clone(&parts.folders));
        let cache_dir: Arc<dyn Fn() -> PathBuf + Send + Sync> = Arc::new(move || shelf.dir(&chosen, &settings));
        Self {
            shelf,
            config: Arc::clone(&parts.config),
            report: Arc::clone(&parts.report),
            folders: Arc::clone(&parts.folders),
            off: Arc::clone(&parts.off),
            view: Arc::clone(&parts.view),
            relocation: Arc::clone(&parts.relocation),
            clock: Arc::clone(&parts.clock),
            http: Arc::clone(&parts.http),
            downloaded: DownloadedFiles::new(cache_dir),
            splits: Arc::clone(&parts.splits),
            disks: Arc::clone(&parts.disks),
            room_maker: OnceLock::new(),
            copying: Mutex::new(BTreeMap::new()),
            in_flight: Mutex::new(BTreeSet::new()),
        }
    }

    /// Where the cache lies when the board chose no folder for it: `modelsBasePath` of `config.json`, else `~/.llama-model-cache`.
    pub(super) fn own_cache_dir(config: &ScoutConfig) -> PathBuf {
        let base = Coerce::strip(&config.text("modelsBasePath")).to_string();
        if !base.is_empty() {
            return Self::expanded(&base);
        }
        Self::home().join(".llama-model-cache")
    }

    /// Where this shelf is now.
    pub fn cache_dir(&self) -> PathBuf {
        self.shelf.dir(&self.folders, &self.config)
    }

    /// Whether this shelf lies in a folder the board chose.
    pub fn folder_chosen(&self) -> bool {
        self.shelf.chosen(&self.folders)
    }

    /// Where the model cache lies by itself: the folder it goes back to when the board's choice is removed.
    pub fn cache_dir_by_itself(&self) -> PathBuf {
        Self::own_cache_dir(&self.config)
    }

    /// Where the model cache is now, whichever shelf asks: the folder for Strata's files may not lie in it.
    pub fn model_cache_dir(&self) -> PathBuf {
        Shelf::CACHE.dir(&self.folders, &self.config)
    }

    /// The cache is from now on in `folder`.
    pub fn choose_folder(&self, folder: &Path) {
        self.folders.cache.set(folder);
    }

    /// The folder of the cells' scratch folders: `.cells` in the shelf's folder, hidden, so that a folder the operator chose keeps his own files apart from the scout's. A cell keeps what it makes from
    /// its model on the shelf its model is on.
    pub fn scratch_root(&self) -> PathBuf {
        self.cache_dir().join(Self::SCRATCH)
    }

    /// The folder that holds the scout's user's files.
    pub fn home() -> PathBuf {
        std::env::var_os("HOME").map_or_else(|| PathBuf::from("/"), PathBuf::from)
    }

    /// `expanduser`.
    pub fn expanded(path: &str) -> PathBuf {
        match path.strip_prefix("~/") {
            Some(rest) => Self::home().join(rest),
            None if path == "~" => Self::home(),
            None => PathBuf::from(path),
        }
    }

    pub(super) fn copy_lock(&self, raw: &str) -> Arc<Mutex<()>> {
        let mut locks = self.copying.lock().unwrap_or_else(PoisonError::into_inner);
        Arc::clone(locks.entry(raw.to_string()).or_default())
    }

    pub(super) fn flying(&self, path: &Path, on: bool) {
        let key = Resolved::of(path);
        let mut flying = self.in_flight.lock().unwrap_or_else(PoisonError::into_inner);
        if on {
            flying.insert(key);
        } else {
            flying.remove(&key);
        }
    }

    /// Whether `path` is being written now.
    pub fn is_flying(&self, path: &Path) -> bool {
        self.in_flight.lock().unwrap_or_else(PoisonError::into_inner).contains(&Resolved::of(path))
    }

    /// Where a cell keeps what it makes from its model: `CARAVAN_CELL_SCRATCH`. It lives as the cell's models live.
    pub fn scratch(&self, cell: &str) -> PathBuf {
        self.scratch_root().join(cell)
    }

    /// The cell's scratch folders that are there: its own, and the one a cell of before 2026-11-07 kept under its port.
    pub fn scratches_of(&self, cell: &str) -> Vec<PathBuf> {
        self.scratch_folders().into_iter().filter(|(of, _)| of == cell).map(|(_, folder)| folder).collect()
    }

    /// Removes the cell's scratch folders; true when there was one.
    pub fn clear_scratch(&self, cell: &str) -> bool {
        let folders = self.scratches_of(cell);
        for folder in &folders {
            // What cannot be removed stays until the next start empties it.
            drop(fs::remove_dir_all(folder));
        }
        !folders.is_empty()
    }

    /// Whether a cell's words say its cached file is truncated or corrupted.
    pub fn is_corruption_error(text: &str) -> bool {
        let low = text.to_lowercase();
        Self::CORRUPT_PATTERNS.iter().any(|word| low.contains(word))
    }

    /// A look at a hinted path with a deadline: a library is an NFS mount, and a dead NFS server makes `stat` wait instead of failing. `None` when it did not answer; for a folder its being one, for a file its size.
    fn look(path: &Path, want_dir: bool) -> Option<u64> {
        let (tell, heard) = mpsc::channel();
        let asked = path.to_path_buf();
        let worker = std::thread::Builder::new().name("model-look".into()).spawn(move || {
            let said = match fs::metadata(&asked) {
                Ok(meta) if want_dir => u64::from(meta.is_dir()),
                Ok(meta) if meta.is_file() => meta.len(),
                _ => 0,
            };
            // The asker may have gone: its deadline has passed, and it said so.
            let _heard_or_gone = tell.send(said);
        });
        if worker.is_err() {
            return None;
        }
        match heard.recv_timeout(Self::PROBE) {
            Ok(said) => Some(said),
            Err(_) => {
                Log::line(&format!(
                    "[llama-node] {} did not answer in {} s — not reading it in place",
                    path.display(),
                    Self::PROBE.as_secs()
                ));
                None
            }
        }
    }

    /// The file where the controller reads it, when this machine has the same one at that path: read there, no copy, not written down as downloaded, never deleted. `None` when the hint names
    /// nothing here, or another file: its size differs.
    pub fn in_place(raw: &str, hint: Option<&Value>) -> Option<PathBuf> {
        let hint = hint.filter(|hint| hint.is_object())?;
        let said = Coerce::stripped(hint.get("path"));
        if said.is_empty() {
            return None;
        }
        let path = Self::expanded(&Coerce::text(hint.get("path")));
        if !path.is_absolute() {
            return None;
        }
        let want_dir = Coerce::truthy(hint.get("dir"));
        let hit = Self::look(&path, want_dir).filter(|hit| *hit != 0)?;
        // absent-ok: `int(hint.get("size") or 0)`: a hint of no size says nothing to differ from.
        let size = Coerce::int_or_zero(hint.get("size")).unwrap_or(0);
        if !want_dir && size != 0 && hit != size as u64 {
            Log::line(&format!(
                "[llama-node] {raw}: {} is here, but it is not the controller's file ({hit} bytes, not {size}) — not reading it in place",
                path.display()
            ));
            return None;
        }
        Some(path)
    }

    /// A local path to the model file. The hint's file when this machine has it; an absolute path that exists; a copy here when `use_cache`; else a fresh copy from the controller, over a file this scout
    /// downloaded and never over another. The first part of a
    /// split GGUF brings the other parts: into the cache beside it, or found beside it where it is read in place, refused when one is missing.
    pub fn ensure(&self, raw: &str, fetch: &Fetch) -> Result<PathBuf, AppError> {
        // Asked before the first byte: a start that asks for parts the split does not have is refused whole.
        let parts = self.splits.brought(raw, fetch.hint.as_ref())?;
        // A first part of another size is another model: the parts beside it are not joined to it.
        let renewed = self.copy_differs(&self.cache_dir().join(raw), fetch.hint.as_ref()).is_some();
        let first = self.ensure_file(raw, fetch)?;
        let (_, rest) = parts.split_at(1.min(parts.len()));
        if rest.is_empty() || first.is_dir() {
            return Ok(first);
        }
        if !self.in_cache(&first) {
            if self.view.holds(&first) {
                for part in rest {
                    self.view.file(part, None)?;
                }
            }
            let folder = first.parent().unwrap_or(Path::new("."));
            let name_of =
                |part: &String| Path::new(part).file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
            if let Some(missing) = rest.iter().find(|part| !folder.join(name_of(part)).is_file()) {
                let first_name = first.file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
                return Err(AppError::with_status(
                    format!("{first_name} is read at {}, but its part {} is not there", folder.display(), name_of(missing)),
                    409,
                ));
            }
            return Ok(first);
        }
        let count = rest.len() + 1;
        for (at, part) in rest.iter().enumerate() {
            let name = Path::new(part).file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
            let label = format!("{name} ({}/{count})", at + 2);
            self.ensure_file(part, &Fetch { label, hint: None, use_cache: fetch.use_cache && !renewed, ..fetch.clone() })?;
        }
        Ok(first)
    }

    /// Whether `path` is inside the cache.
    pub fn in_cache(&self, path: &Path) -> bool {
        Resolved::of(path).starts_with(Resolved::of(&self.cache_dir()))
    }

    /// The model with no copy of it here: from the folder the operator named, or through the controller.
    fn without_a_copy(&self, raw: &str, fetch: &Fetch) -> Result<PathBuf, AppError> {
        if self.off.from_folder() {
            return self.off.read_from_library(raw, fetch.hint.as_ref());
        }
        if fetch.hint.as_ref().is_some_and(|hint| Coerce::truthy(hint.get("dir"))) {
            return self.view.folder_of(raw, &self.folder_listing(raw)?);
        }
        self.view.file(raw, fetch.hint.as_ref())
    }

    fn ensure_file(&self, raw: &str, fetch: &Fetch) -> Result<PathBuf, AppError> {
        if let Some(here) = self.shelf.reads_in_place.then(|| Self::in_place(raw, fetch.hint.as_ref())).flatten() {
            let name = Path::new(raw).file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
            Log::line(&format!("[llama-node] {name}: read in place — {}", here.display()));
            return Ok(here);
        }
        let said = Self::expanded(raw);
        if said.is_absolute() && said.exists() {
            return Ok(said);
        }
        if self.shelf.can_be_off && self.off.is_off() {
            let here = self.without_a_copy(raw, fetch)?;
            Log::line(&format!("[llama-node] {raw}: the cache is off, read from {}", here.display()));
            return Ok(here);
        }
        if fetch.hint.as_ref().is_some_and(|hint| Coerce::truthy(hint.get("dir"))) {
            return self.ensure_folder(raw, fetch);
        }
        let local = self.cache_dir().join(raw);
        // One copy of a file at a time: a stop does not end the copy it interrupts, and a start that follows at once waits for it and finds the file whole.
        let lock = self.copy_lock(raw);
        let _held = lock.lock().unwrap_or_else(PoisonError::into_inner);
        if fetch.use_cache && local.exists() {
            let Some((here, there)) = self.copy_differs(&local, fetch.hint.as_ref()) else {
                return Ok(local);
            };
            Log::line(&format!(
                "[llama-node] {raw}: the copy here is not the controller's file ({here} bytes, not {there}) — bringing it again"
            ));
        }
        // Whose the file there is, is asked before a byte is fetched: a copy would take its name and a place on this scout's record, and the next clean-up would take the file.
        if local.symlink_metadata().is_ok() && !self.downloaded.has(&local) {
            return Err(Self::not_ours(&local));
        }
        self.controller(raw)?;
        let label = if fetch.label.is_empty() {
            Path::new(raw).file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned())
        } else {
            fetch.label.clone()
        };
        if let Some(parent) = local.parent() {
            fs::create_dir_all(parent).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        }
        let temporary = local.with_extension("tmp");
        self.download(raw, &local, &temporary, &label, fetch, true)
    }

    /// The controller's address, or the refusal that names what could not be fetched without it.
    pub(super) fn controller(&self, what: &str) -> Result<String, AppError> {
        let controller = self.config.text("controllerUrl");
        let controller = controller.trim_end_matches('/');
        if controller.is_empty() {
            return Err(AppError::with_status(format!("model not found locally and controllerUrl not set: {what}"), 404));
        }
        Ok(controller.to_string())
    }

    /// The fields a request to the controller carries.
    pub fn token_fields(&self) -> Vec<(&'static str, String)> {
        let token = self.config.token();
        if token.is_empty() { Vec::new() } else { vec![("X-Caravan-Token", token)] }
    }
}
