//! One persisted document. A document held in memory stands behind a lock, and a change is a closure: nothing can hold it across a call to the network.

use files::AtomicFile;
use os::LocalTime;
use rules::PythonJson;
use serde_json::{Map, Value};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard, PoisonError};

/// The empty object a document starts as.
pub type Document = Map<String, Value>;

/// A file we cannot USE, copied aside once before anything overwrites it.
pub struct Unreadable;

impl Unreadable {
    /// `<stem>.json.unreadable-<stamp>` beside it, with the file's own permissions: one of these documents holds the API keys. Once, not once per read: a caravan that keeps failing on the same file must not fill the folder. Failures are kept quiet on purpose: this is a net around a read, and a net that can refuse the read is worse than no net.
    pub fn keep(path: &Path, stamp: &str) {
        let (Some(parent), Some(stem)) = (path.parent(), path.file_stem().map(|stem| stem.to_string_lossy().into_owned())) else {
            return;
        };
        let start = format!("{stem}.json.unreadable-");
        // absent-ok: a folder that does not list has no copy to find, and the copy below fails the same way, in silence.
        let there = std::fs::read_dir(parent)
            .map(|names| names.flatten().any(|name| name.file_name().to_string_lossy().starts_with(&start)))
            .unwrap_or(false);
        if !there {
            // In silence, as the comment above says.
            drop(std::fs::copy(path, parent.join(format!("{start}{stamp}"))));
        }
    }

    /// `%Y%m%d-%H%M%S` of the local time.
    pub fn stamp(epoch: i64) -> String {
        LocalTime::of(epoch).map_or_else(|| epoch.to_string(), |local| local.compact())
    }
}

/// A document on disk, loaded once and changed in place.
pub struct Store {
    path: PathBuf,
    doc: Mutex<Document>,
}

impl Store {
    /// The file's contents, or empty for a missing file AND for an unreadable one: a corrupt document is a bad start, not a dead process. A file that holds no object reads as empty too.
    pub fn read_file(path: &Path) -> Document {
        let Ok(raw) = std::fs::read(path) else {
            return Document::new();
        };
        match serde_json::from_slice(&raw) {
            Ok(Value::Object(fields)) => fields,
            _ => Document::new(),
        }
    }

    /// The store of the file at `path`.
    pub fn open(path: PathBuf) -> Self {
        let doc = Self::read_file(&path);
        Self { path, doc: Mutex::new(doc) }
    }

    /// Where it lives.
    pub fn path(&self) -> &Path {
        &self.path
    }

    fn locked(&self) -> MutexGuard<'_, Document> {
        self.doc.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// A look at the document.
    pub fn read<R>(&self, look: impl FnOnce(&Document) -> R) -> R {
        look(&self.locked())
    }

    /// A change of the document, in memory: the save is the caller's.
    pub fn change<R>(&self, edit: impl FnOnce(&mut Document) -> R) -> R {
        edit(&mut self.locked())
    }

    /// A copy of the document.
    pub fn snapshot(&self) -> Document {
        self.locked().clone()
    }

    /// The document on disk: indent=2 because this file is read and hand-edited during incidents.
    pub fn save(&self) -> std::io::Result<()> {
        let text = PythonJson::indented(&Value::Object(self.snapshot()));
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        AtomicFile::write(&self.path, text.as_bytes())
    }

    /// Replaces every value.
    pub fn refill(&self, fresh: Document) {
        *self.locked() = fresh;
    }

    /// A map under `name`, guaranteed to exist and to have `keys`: what a seed does. In place, and never over a value that is there.
    pub fn section<'doc>(doc: &'doc mut Document, name: &str, keys: &[&str]) -> &'doc mut Document {
        let section = doc.entry(name.to_string()).or_insert_with(|| Value::Object(Map::new()));
        if !section.is_object() {
            *section = Value::Object(Map::new());
        }
        match section {
            Value::Object(fields) => {
                for key in keys {
                    fields.entry((*key).to_string()).or_insert_with(|| Value::Object(Map::new()));
                }
                fields
            }
            _ => unreachable!("it was made an object above"),
        }
    }
}
