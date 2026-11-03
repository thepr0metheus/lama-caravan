//! A model read through the controller, with no copy on this machine and no share mounted on it (the owner, 2026-11-02: "by default the long way: the folder with the models, then the caravan, then the scout and its video memory"). A program reads a file and nothing else, so the scout shows it one: a folder of this scout's own, mounted through FUSE, whose files are the controller's and whose bytes come from it as they are read.

pub mod kernel;
pub mod reader;
pub mod session;
#[cfg(test)]
mod tests;
pub mod tree;

use crate::log::Log;
use crate::models::files::Resolved;
use os::FuseLink;
use reader::{ControllerFiles, ControllerReader};
use rules::{AppError, Coerce};
use serde_json::Value;
use session::{GivenBytes, ViewSession};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, PoisonError};
use tree::ViewTree;

/// The view on this machine.
pub struct LibraryView {
    folder: PathBuf,
    can: fn() -> bool,
    files: Arc<ControllerFiles>,
    tree: Arc<Mutex<ViewTree>>,
    given: Arc<GivenBytes>,
    /// Whether a session answers the mount. It says false when the mount goes.
    alive: Arc<AtomicBool>,
    mounting: Mutex<()>,
}

impl LibraryView {
    /// The view in `folder`, of these files: nothing is mounted until a start asks.
    pub fn new(folder: PathBuf, files: ControllerFiles) -> Self {
        Self::by(folder, files, FuseLink::available)
    }

    /// The same, with this word on whether the machine can.
    pub fn by(folder: PathBuf, files: ControllerFiles, can: fn() -> bool) -> Self {
        Self {
            folder,
            can,
            files: Arc::new(files),
            tree: Arc::default(),
            given: Arc::default(),
            alive: Arc::new(AtomicBool::new(false)),
            mounting: Mutex::new(()),
        }
    }

    /// From now on this word on whether the machine can: a test's.
    #[cfg(test)]
    pub fn take_word(&mut self, can: fn() -> bool) {
        self.can = can;
    }

    /// Whether this machine can show files this way: what the board asks before it offers the way.
    pub fn possible(&self) -> bool {
        (self.can)()
    }

    /// Where the view is.
    pub fn folder(&self) -> &Path {
        &self.folder
    }

    /// Whether `path` is in the view.
    pub fn holds(&self, path: &Path) -> bool {
        Resolved::of(path).starts_with(Resolved::of(&self.folder))
    }

    /// A mount standing, a session answering it. What the last run left has nobody behind it: every read of it fails, so it goes first.
    fn mounted(&self) -> Result<(), AppError> {
        let _one_at_a_time = self.mounting.lock().unwrap_or_else(PoisonError::into_inner);
        if self.alive.load(Ordering::SeqCst) {
            return Ok(());
        }
        FuseLink::unmount(&self.folder);
        fs::create_dir_all(&self.folder)
            .map_err(|error| AppError::with_status(format!("{}: {error}", self.folder.display()), 500))?;
        let link = FuseLink::mount(&self.folder, "caravan-models").map_err(|words| {
            AppError::with_status(format!("this machine cannot read a model through the controller: {words} — install fuse3, or read the library from a mounted folder"), 409)
        })?;
        let session = ViewSession::new(
            Arc::clone(&self.tree),
            Arc::new(ControllerReader::new(Arc::clone(&self.files))),
            Arc::clone(&self.given),
        );
        let alive = Arc::clone(&self.alive);
        self.alive.store(true, Ordering::SeqCst);
        let serving = std::thread::Builder::new().name("library-view".to_string()).spawn(move || {
            let (device, staying) = link.parts();
            session.serve(device);
            alive.store(false, Ordering::SeqCst);
            drop(staying);
        });
        if let Err(error) = serving {
            self.alive.store(false, Ordering::SeqCst);
            return Err(AppError::with_status(format!("no thread for the view: {error}"), 500));
        }
        Log::line(&format!("[llama-node] models are read through the controller, in {}", self.folder.display()));
        Ok(())
    }

    /// What programs were given through the view of these places, since a start last asked for them; `None` when nothing of them came this way.
    pub fn given_of(&self, places: &[String]) -> Option<u64> {
        self.given.of(places)
    }

    /// The controller's file `raw` as a path here. `hint` saves asking what it weighs.
    pub fn file(&self, raw: &str, hint: Option<&Value>) -> Result<PathBuf, AppError> {
        self.mounted()?;
        self.given.begin(raw);
        let said = hint
            .filter(|hint| hint.is_object())
            .and_then(|hint| hint.get("size"))
            .and_then(Value::as_u64)
            .filter(|size| *size != 0);
        let size = match said {
            Some(size) => size,
            None => self.files.size_of(raw)?,
        };
        self.tree.lock().unwrap_or_else(PoisonError::into_inner).offer_file(raw, size)?;
        Ok(self.folder.join(raw))
    }

    /// The controller's model folder `raw` as a path here: its listing, its files and its links.
    pub fn folder_of(&self, raw: &str, listing: &Value) -> Result<PathBuf, AppError> {
        self.mounted()?;
        self.given.begin(raw);
        // absent-ok: a listing with no such rows has none of them.
        let rows = |key: &str| listing.get(key).and_then(Value::as_array).cloned().unwrap_or_default();
        let mut tree = self.tree.lock().unwrap_or_else(PoisonError::into_inner);
        for row in rows("files") {
            // absent-ok: a row of no size is a file of none, as the listing of an empty file says.
            let size = row.get("size").and_then(Value::as_u64).unwrap_or(0);
            tree.offer_file(&format!("{raw}/{}", Coerce::text(row.get("path"))), size)?;
        }
        for row in rows("links") {
            tree.offer_link(&format!("{raw}/{}", Coerce::text(row.get("path"))), &Coerce::text(row.get("target")))?;
        }
        Ok(self.folder.join(raw))
    }
}
